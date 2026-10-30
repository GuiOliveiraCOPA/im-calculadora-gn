"""Validação da base tarifária e repositório em memória com recarga em segundo plano.

Princípio: a tela nunca espera o Databricks. A base é lida na partida e a cada
GN_RECARGA_MINUTOS em uma thread; as requisições usam a última base válida em memória.
Base inválida nunca calcula: uma recarga inválida é descartada e a anterior continua.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from calculadora import cache_local

CAMPOS_TEXTO = ("uf", "segmento_copa", "concessionaria", "segmento", "preco_concessionaria")
CAMPOS_NUMERICOS = ("faixa_min", "faixa_max", "tarifa", "termo_fixo", "pis_cofins", "icms", "ordem")
# Campos novos do contrato da Gold: opcionais (a fixture antiga não os tem), mas validados quando vêm.
CAMPOS_DATA_OPCIONAIS = ("dt_delib", "vigencia_inicio", "atualizado_em")
STATUS_ATUALIZACAO = ("atualizada", "desatualizada")
ORIGENS_VALOR = ("execucao_atual", "anterior_tabela_ausente", "anterior_tabela_invalida", "base_manual")
PARAMETROS_OBRIGATORIOS = ("FATOR_GN_PARA_GLP", "FATOR_GLP_PARA_GN")
# Opcional: sem ela, vale a constante do calculo.py.
PARAMETROS_OPCIONAIS = ("ALIQUOTA_MONOFASICA_GLP",)

logger = logging.getLogger("calculadora.dados")


class TarifasInvalidas(Exception):
    """A base tarifária não pode ser usada pela calculadora."""


@dataclass(frozen=True)
class BaseTarifaria:
    records: tuple[dict, ...]
    generated_at: str
    source: str
    origem: str = "json"  # databricks | cache_local | json
    carregado_em: str = ""  # ISO 8601 em UTC: quando a base foi lida da fonte
    parametros: dict = field(default_factory=dict)  # vazio: o cálculo usa as constantes do calculo.py


def _numero_valido(valor) -> bool:
    # bool é subclasse de int: True/False não podem passar como número
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def validar_registros(records) -> list[str]:
    """Retorna a lista de problemas encontrados (vazia quando a base está íntegra)."""
    if not isinstance(records, list) or not records:
        return ["Nenhum registro de tarifa encontrado."]

    erros = []
    for i, r in enumerate(records):
        prefixo = f"registro {i} ({r.get('uf')} | {r.get('concessionaria')} | {r.get('segmento')})"
        for campo in CAMPOS_TEXTO:
            if not isinstance(r.get(campo), str):
                erros.append(f"{prefixo}: campo '{campo}' deve ser texto ({r.get(campo)!r})")
        for campo in CAMPOS_NUMERICOS:
            if not _numero_valido(r.get(campo)):
                erros.append(f"{prefixo}: campo '{campo}' deve ser numérico ({r.get(campo)!r})")
        if not isinstance(r.get("cascata"), bool):
            erros.append(f"{prefixo}: campo 'cascata' deve ser true/false ({r.get('cascata')!r})")

        if _numero_valido(r.get("faixa_min")) and _numero_valido(r.get("faixa_max")):
            if r["faixa_min"] > r["faixa_max"]:
                erros.append(f"{prefixo}: faixa_min maior que faixa_max")
        for campo in ("pis_cofins", "icms"):
            if _numero_valido(r.get(campo)) and not 0 <= r[campo] < 1:
                erros.append(f"{prefixo}: {campo} fora do intervalo 0–1 ({r[campo]})")
        if _numero_valido(r.get("tarifa")) and r["tarifa"] < 0:
            erros.append(f"{prefixo}: tarifa negativa")

        for campo in CAMPOS_DATA_OPCIONAIS:
            if r.get(campo) is not None and not isinstance(r[campo], str):
                erros.append(f"{prefixo}: campo '{campo}' deve ser data em texto ou nulo ({r[campo]!r})")
        if "status_atualizacao" in r and r["status_atualizacao"] not in STATUS_ATUALIZACAO:
            erros.append(f"{prefixo}: status_atualizacao inválido ({r['status_atualizacao']!r})")
        if "origem_valor" in r and r["origem_valor"] not in ORIGENS_VALOR:
            erros.append(f"{prefixo}: origem_valor inválido ({r['origem_valor']!r})")
    return erros


def validar_parametros(parametros) -> list[str]:
    """Parâmetros da Gold. None (fixture sem parâmetros) é aceito: o cálculo usa as constantes."""
    if parametros is None:
        return []
    if not isinstance(parametros, dict):
        return ["Parâmetros de cálculo em formato inválido."]
    erros = []
    for nome in PARAMETROS_OBRIGATORIOS + PARAMETROS_OPCIONAIS:
        if nome in PARAMETROS_OPCIONAIS and nome not in parametros:
            continue
        valor = parametros.get(nome)
        if not _numero_valido(valor) or valor <= 0:
            erros.append(f"parâmetro {nome} ausente ou inválido ({valor!r})")
    return erros


def montar_base(payload: dict, origem: str, carregado_em: str) -> BaseTarifaria:
    """Valida o payload de uma fonte; levanta TarifasInvalidas com os primeiros problemas."""
    records = payload.get("records") if isinstance(payload, dict) else None
    parametros = payload.get("parametros") if isinstance(payload, dict) else None
    erros = validar_registros(records) + validar_parametros(parametros)
    if erros:
        resumo = "\n".join(erros[:20])
        extra = f"\n... e mais {len(erros) - 20} problema(s)." if len(erros) > 20 else ""
        raise TarifasInvalidas(f"Base tarifária inválida ({payload.get('source', origem)}):\n{resumo}{extra}")

    return BaseTarifaria(
        records=tuple(records),
        generated_at=str(payload.get("generated_at", "")),
        source=str(payload.get("source", "")),
        origem=origem,
        carregado_em=carregado_em,
        parametros={nome: parametros[nome] for nome in PARAMETROS_OBRIGATORIOS + PARAMETROS_OPCIONAIS
                    if nome in parametros} if parametros else {},
    )


def carregar_base(caminho: Path) -> BaseTarifaria:
    """Lê e valida um arquivo JSON de tarifas (fixtures e testes)."""
    from calculadora.fonte_json import FonteJson

    return montar_base(FonteJson(caminho).carregar(), "json", _agora_iso())


def situacao_da_selecao(records, uf, segmento_copa, concessionaria, segmento) -> dict | None:
    """Datas e avisos das Classes da combinação escolhida (campos novos da Gold)."""
    linhas = [
        r for r in records
        if r["uf"] == uf and r["segmento_copa"] == segmento_copa
        and r["concessionaria"] == concessionaria and r["segmento"] == segmento
    ]
    if not linhas:
        return None
    atualizacoes = [r["atualizado_em"] for r in linhas if r.get("atualizado_em")]
    vigencias = [r["vigencia_inicio"] for r in linhas if r.get("vigencia_inicio")]
    origens = {r.get("origem_valor") for r in linhas}
    deliberacoes = sorted({r["deliberacao"] for r in linhas if r.get("deliberacao")})
    return {
        "atualizado_em": max(atualizacoes, default=None),
        "vigencia_inicio": max(vigencias, default=None),
        "deliberacao": ", ".join(deliberacoes) or None,  # nula na Gold enquanto a ingestão não publicar
        "desatualizada": any(r.get("status_atualizacao") == "desatualizada" for r in linhas),
        "base_manual": "base_manual" in origens,
        "valor_mantido": bool(origens & {"anterior_tabela_ausente", "anterior_tabela_invalida"}),
    }


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _agora_iso() -> str:
    return _agora().isoformat(timespec="seconds")


class RepositorioTarifas:
    """Mantém a última base válida em memória e a recarrega da fonte em segundo plano."""

    def __init__(self, fonte, cache_path: Path | None = None, recarga_minutos: int = 30,
                 max_idade_horas: int = 72, relogio=_agora):
        self.fonte = fonte
        self.cache_path = Path(cache_path) if cache_path else None
        self.recarga_minutos = recarga_minutos
        self.max_idade_horas = max_idade_horas
        self._relogio = relogio
        self._lock = threading.Lock()
        self._base: BaseTarifaria | None = None
        self._ultimo_erro = ""
        self._ultima_tentativa = ""
        self._ultima_recarga_ok = True
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ consulta
    def obter(self) -> BaseTarifaria:
        base = self._base
        if base is None:
            motivo = self._ultimo_erro or "a primeira carga ainda não terminou."
            raise TarifasInvalidas(f"Base tarifária ainda não carregada: {motivo}")
        return base

    def idade_horas(self) -> float | None:
        base = self._base
        if base is None or not base.carregado_em:
            return None
        return (self._relogio() - datetime.fromisoformat(base.carregado_em)).total_seconds() / 3600

    def base_antiga(self) -> bool:
        idade = self.idade_horas()
        return idade is not None and idade > self.max_idade_horas

    def estado(self) -> dict:
        """Situação para o /saude, sem dados sensíveis."""
        base = self._base
        with self._lock:
            ultimo_erro, ultima_tentativa, recarga_ok = self._ultimo_erro, self._ultima_tentativa, self._ultima_recarga_ok
        if base is None:
            status = "sem_base"
        elif base.origem == "cache_local" or self.base_antiga() or not recarga_ok:
            status = "degradado"
        else:
            status = "ok"
        idade = self.idade_horas()
        return {
            "status": status,
            "origem": base.origem if base else None,
            "fonte": getattr(self.fonte, "origem", None),
            "registros": len(base.records) if base else 0,
            "generated_at": base.generated_at if base else None,
            "carregado_em": base.carregado_em if base else None,
            "idade_horas": round(idade, 2) if idade is not None else None,
            "ultima_tentativa": ultima_tentativa or None,
            # Só o começo da mensagem: o texto completo fica no log.
            "ultimo_erro": ultimo_erro[:300] or None,
        }

    # ------------------------------------------------------------------ carga
    def recarregar(self) -> bool:
        """Lê a fonte; se a base for válida, troca a de memória e grava a cópia local."""
        tentativa = _agora_iso()
        try:
            payload = self.fonte.carregar()
            carregado_em = self._relogio().isoformat(timespec="seconds")
            base = montar_base(payload, self.fonte.origem, carregado_em)
        except Exception as exc:  # rede, autenticação, warehouse ou base inválida: mantém a atual
            mensagem = f"{type(exc).__name__}: {exc}"
            logger.error("Falha ao carregar a base (%s); mantida a base atual. %s", self.fonte.origem, mensagem)
            with self._lock:
                self._ultimo_erro, self._ultima_tentativa, self._ultima_recarga_ok = mensagem, tentativa, False
            return False

        self._base = base
        with self._lock:
            self._ultimo_erro, self._ultima_tentativa, self._ultima_recarga_ok = "", tentativa, True
        logger.info("Base carregada de %s: %d registros, gerada em %s.", base.origem, len(base.records), base.generated_at)
        if self.cache_path:
            try:
                cache_local.gravar(self.cache_path, payload, base.origem, carregado_em)
            except OSError as exc:
                logger.warning("Não consegui gravar a cópia local em %s: %s", self.cache_path, exc)
        return True

    def carregar_cache(self) -> bool:
        """Usa a cópia local enquanto a fonte não responde (só se ainda não há base)."""
        if not self.cache_path or self._base is not None:
            return False
        conteudo = cache_local.ler(self.cache_path)
        if conteudo is None:
            return False
        try:
            base = montar_base(conteudo["payload"], "cache_local", str(conteudo.get("carregado_em", "")))
        except TarifasInvalidas as exc:
            logger.error("Cópia local inválida, ignorada: %s", exc)
            return False
        self._base = base
        logger.warning("Usando a cópia local de %s até a fonte responder.", base.carregado_em)
        return True

    def iniciar(self, carga_sincrona: bool = False) -> None:
        """Cópia local primeiro (rápida) e depois a fonte, na thread de recarga."""
        self.carregar_cache()
        if carga_sincrona:
            self.recarregar()
        self._thread = threading.Thread(target=self._laco, args=(not carga_sincrona,), name="recarga-tarifas",
                                        daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()

    def _laco(self, carregar_ja: bool) -> None:
        if carregar_ja:
            self.recarregar()
        while True:
            # Sem base ou com falha, tenta de novo em até 5 minutos (warehouse frio, rede instável).
            minutos = self.recarga_minutos if self._ultima_recarga_ok and self._base else min(self.recarga_minutos, 5)
            if self._parar.wait(minutos * 60):
                return
            self.recarregar()
