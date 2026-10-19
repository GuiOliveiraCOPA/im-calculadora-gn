"""Agendamento do ETL: horário diário e dias da semana, editáveis pela tela /interno/etl.

O agendamento fica em <estado_dir>/agendamento.json. O agendador é uma thread do próprio
servidor que confere o horário a cada 30 segundos. Execuções perdidas (servidor desligado no
horário) não são recuperadas depois; rode manualmente pela tela se precisar.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from etl.executor import EtlEmExecucao, ExecutorEtl, _gravar_json

DIAS_SEMANA = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")  # índice = datetime.weekday()
AGENDAMENTO_PADRAO = {"ativo": True, "horario": "00:00", "dias": list(range(7)), "mesmo_com_erro": False}
RESPONSAVEL_AGENDADO = "Agendamento"
INTERVALO_VERIFICACAO = 30  # segundos

log = logging.getLogger(__name__)


class AgendamentoInvalido(ValueError):
    pass


def validar_agendamento(dados: dict) -> dict:
    horario = str(dados.get("horario", "")).strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", horario):
        raise AgendamentoInvalido("Horário inválido. Use HH:MM, de 00:00 a 23:59.")
    try:
        dias = sorted({int(d) for d in dados.get("dias", [])})
    except (TypeError, ValueError) as exc:
        raise AgendamentoInvalido("Dias da semana inválidos.") from exc
    if any(d not in range(7) for d in dias):
        raise AgendamentoInvalido("Dias da semana inválidos.")
    ativo = bool(dados.get("ativo"))
    if ativo and not dias:
        raise AgendamentoInvalido("Escolha pelo menos um dia da semana ou desative o agendamento.")
    return {"ativo": ativo, "horario": horario, "dias": dias, "mesmo_com_erro": bool(dados.get("mesmo_com_erro"))}


def carregar_agendamento(caminho: Path) -> dict:
    try:
        return validar_agendamento(json.loads(Path(caminho).read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError, AgendamentoInvalido, AttributeError):
        return dict(AGENDAMENTO_PADRAO)


def salvar_agendamento(caminho: Path, dados: dict) -> dict:
    agendamento = validar_agendamento(dados)
    _gravar_json(Path(caminho), agendamento)
    return agendamento


def proxima_execucao(agendamento: dict, apos: datetime) -> datetime | None:
    """Primeiro horário agendado estritamente depois de `apos` (None se desativado)."""
    if not agendamento.get("ativo") or not agendamento.get("dias"):
        return None
    hora, minuto = map(int, agendamento["horario"].split(":"))
    for dias_a_frente in range(8):
        candidato = (apos + timedelta(days=dias_a_frente)).replace(hour=hora, minute=minuto, second=0, microsecond=0)
        if candidato > apos and candidato.weekday() in agendamento["dias"]:
            return candidato
    return None


def descrever(agendamento: dict) -> str:
    if not agendamento.get("ativo"):
        return "Desativado"
    dias = agendamento["dias"]
    quando = "todos os dias" if len(dias) == 7 else ", ".join(DIAS_SEMANA[d] for d in dias)
    return f"{quando} às {agendamento['horario']}"


class Agendador(threading.Thread):
    """Dispara o ETL nos horários do agendamento.json (relido a cada verificação)."""

    def __init__(self, executor: ExecutorEtl, caminho_agendamento: Path):
        super().__init__(name="etl-agendador", daemon=True)
        self.executor = executor
        self.caminho = Path(caminho_agendamento)
        self._parar = threading.Event()
        self._referencia = datetime.now()
        self._assinatura = self._assinatura_arquivo()

    def _assinatura_arquivo(self):
        try:
            stat = self.caminho.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            return None

    def proxima(self) -> datetime | None:
        return proxima_execucao(carregar_agendamento(self.caminho), self._referencia)

    def verificar(self, agora: datetime | None = None) -> bool:
        """Uma rodada de verificação. Devolve True se disparou o ETL."""
        agora = agora or datetime.now()
        assinatura = self._assinatura_arquivo()
        if assinatura != self._assinatura:
            # Agendamento alterado: conta a partir de agora (não dispara um horário que já passou hoje).
            self._assinatura = assinatura
            self._referencia = agora
            return False

        agendamento = carregar_agendamento(self.caminho)
        prevista = proxima_execucao(agendamento, self._referencia)
        if prevista is None or prevista > agora:
            return False
        self._referencia = agora
        try:
            self.executor.iniciar(origem="agendamento", responsavel=RESPONSAVEL_AGENDADO,
                                  mesmo_com_erro=agendamento["mesmo_com_erro"])
            log.info("ETL agendado iniciado (%s).", prevista.strftime("%Y-%m-%d %H:%M"))
            return True
        except EtlEmExecucao:
            log.warning("ETL agendado para %s ignorado: já havia uma execução em andamento.", prevista)
            return False

    def run(self) -> None:
        log.info("Agendador do ETL ativo. Próxima execução: %s", self.proxima())
        while not self._parar.wait(INTERVALO_VERIFICACAO):
            try:
                self.verificar()
            except Exception:  # o agendador não pode morrer por um erro pontual
                log.exception("Erro no agendador do ETL")

    def parar(self) -> None:
        self._parar.set()
