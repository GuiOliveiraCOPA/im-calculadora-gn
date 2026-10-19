"""Execução do processo do IM, no mesmo roteiro do AtualizarDados.sh.

1. Prepara o ambiente (confere as bibliotecas e o navegador do Selenium).
2. Extração e consolidação: Fonte_Dados/codigo_central.py (os 17 extratores tabela_*.py).
3. Base da calculadora: 3_Manutencao/atualizar_calculadora.py (cruza com o Tarifario_GN.xlsx).
4. Publicação: o tarifas.json gerado só substitui o da calculadora se passar na validação
   de calculadora/dados.py. Se falhar, a calculadora continua com a base anterior.

Como no AtualizarDados.sh, se algum extrator falhar a base da calculadora não é atualizada,
a menos que a execução peça "mesmo_com_erro".
"""

from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from calculadora.dados import TarifasInvalidas, carregar_base
from etl.config import ConfiguracaoEtl

FORMATO_DATA = "%Y-%m-%d %H:%M:%S"
NOME_LOG = re.compile(r"^Execucao_\d{3}_\d{4}-\d{2}-\d{2}_[A-Za-z0-9._-]+\.log$")
LIMITE_HISTORICO = 200
IMPORTS_PROCESSO = "import openpyxl, pandas, requests, bs4, pdfplumber, fitz, selenium"
NAVEGADORES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
WRAPPER_ATUALIZAR = Path(__file__).resolve().parent / "rodar_atualizar_calculadora.py"

RE_RODANDO = re.compile(r"^Rodando (\w+)\.\.\.$")
RE_STATUS_UF = re.compile(r"^Status: (.+)$")


class EtlEmExecucao(Exception):
    """Já existe uma execução do ETL em andamento."""


def _agora() -> str:
    return datetime.now().strftime(FORMATO_DATA)


def _gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporario.replace(caminho)


class ExecutorEtl:
    """Roda uma execução por vez, em segundo plano, e mantém o histórico."""

    def __init__(self, config: ConfiguracaoEtl):
        self.config = config
        self._lock_execucao = threading.Lock()
        self._lock_historico = threading.Lock()
        self._atual: dict | None = None
        self._marcar_interrompidas()

    # ------------------------------------------------------------------ consulta
    def em_execucao(self) -> dict | None:
        return dict(self._atual) if self._atual else None

    def historico(self) -> list[dict]:
        try:
            dados = json.loads(self.config.historico_json.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return dados if isinstance(dados, list) else []

    def logs_disponiveis(self) -> list[dict]:
        """Todos os logs de Execucoes_CMD, inclusive os gerados pelo .bat/.sh do IM."""
        if not self.config.log_dir.is_dir():
            return []
        logs = [p for p in self.config.log_dir.iterdir() if p.is_file() and NOME_LOG.match(p.name)]
        logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {"nome": p.name, "tamanho": p.stat().st_size,
             "modificado": datetime.fromtimestamp(p.stat().st_mtime).strftime(FORMATO_DATA)}
            for p in logs
        ]

    def caminho_log(self, nome: str) -> Path | None:
        if not NOME_LOG.match(nome):
            return None
        caminho = self.config.log_dir / nome
        return caminho if caminho.is_file() else None

    # ------------------------------------------------------------------ execução
    def iniciar(self, origem: str, responsavel: str, ufs: str = "", skip_run: bool = False,
                mesmo_com_erro: bool = False) -> dict:
        """Dispara a execução em segundo plano e devolve o registro dela."""
        execucao = self._reservar(origem, responsavel, ufs, skip_run, mesmo_com_erro)
        threading.Thread(target=self._executar, args=(execucao,), name="etl-execucao", daemon=True).start()
        return dict(execucao)

    def executar(self, origem: str, responsavel: str, ufs: str = "", skip_run: bool = False,
                 mesmo_com_erro: bool = False) -> dict:
        """Mesma execução, mas bloqueando até o fim (linha de comando e testes)."""
        execucao = self._reservar(origem, responsavel, ufs, skip_run, mesmo_com_erro)
        self._executar(execucao)
        return execucao

    def _reservar(self, origem, responsavel, ufs, skip_run, mesmo_com_erro) -> dict:
        if not self._lock_execucao.acquire(blocking=False):
            raise EtlEmExecucao("Já existe uma atualização em andamento. Aguarde o fim dela.")
        try:
            responsavel = (responsavel or "").strip() or getpass.getuser()
            ufs = ",".join(uf.strip().upper() for uf in (ufs or "").split(",") if uf.strip())
            self.config.log_dir.mkdir(parents=True, exist_ok=True)
            execucao = {
                "log": self._proximo_nome_log(responsavel),
                "origem": origem,
                "responsavel": responsavel,
                "inicio": _agora(),
                "fim": "",
                "status": "em execução",
                "etapa": "preparação",
                "codigo_saida": None,
                "base_publicada": False,
                "registros": None,
                "generated_at": "",
                "mensagem": "",
                "opcoes": {"ufs": ufs, "skip_run": bool(skip_run), "mesmo_com_erro": bool(mesmo_com_erro)},
                "ufs": [],
            }
            self._atual = execucao
            self._salvar_no_historico(execucao)
            return execucao
        except Exception:
            self._atual = None
            self._lock_execucao.release()
            raise

    def _proximo_nome_log(self, responsavel: str) -> str:
        # Mesmo padrão do AtualizarDados.bat/.sh: Execucao_NNN_AAAA-MM-DD_<responsavel>.log
        data = datetime.now().strftime("%Y-%m-%d")
        usuario = re.sub(r"[^A-Za-z0-9._-]", "_", responsavel) or "etl"
        qtd_hoje = len(list(self.config.log_dir.glob(f"Execucao_*_{data}_*.log")))
        return f"Execucao_{qtd_hoje + 1:03d}_{data}_{usuario}.log"

    def _executar(self, execucao: dict) -> None:
        log_path = self.config.log_dir / execucao["log"]
        status = 1
        try:
            with open(log_path, "w", encoding="utf-8", newline="\n") as log:
                status = self._roteiro(execucao, log)
                log.write(f"\n===== FIM DA EXECUCAO =====\nTermino: {_agora()}\nStatus: {status}\n")
        except Exception as exc:  # falha do próprio orquestrador: registra e libera
            status = 1
            execucao["mensagem"] = f"Falha inesperada no ETL: {exc}"
            try:
                with open(log_path, "a", encoding="utf-8") as log:
                    log.write(f"\nERRO: {execucao['mensagem']}\nStatus: 1\n")
            except OSError:
                pass
        finally:
            execucao["fim"] = _agora()
            execucao["codigo_saida"] = status
            execucao["etapa"] = "fim"
            if execucao["base_publicada"]:
                execucao["status"] = "sucesso" if status == 0 else "parcial"
            else:
                execucao["status"] = "erro"
            self._salvar_no_historico(execucao)
            self._atual = None
            self._lock_execucao.release()

    def _roteiro(self, execucao: dict, log) -> int:
        cfg = self.config
        opcoes = execucao["opcoes"]

        def registrar(*linhas: str) -> None:
            for linha in linhas:
                log.write(linha + "\n")
                print(f"[etl] {linha}", flush=True)
            log.flush()

        computador = socket.gethostname()
        usuario_sistema = getpass.getuser()
        registrar(
            f"Execucao: {execucao['log']}",
            f"Responsavel: {execucao['responsavel']}",
            f"Usuario do sistema: {usuario_sistema}",
            f"Computador: {computador}",
            f"Inicio: {execucao['inicio']}",
            f"Origem: {execucao['origem']}",
            f"Pasta: {cfg.comece_aqui}",
            f"Opcoes: UFs={opcoes['ufs'] or 'todas'} | skip-run={'sim' if opcoes['skip_run'] else 'nao'}"
            f" | calculadora-mesmo-com-erro={'sim' if opcoes['mesmo_com_erro'] else 'nao'}",
            "",
            "===== PREPARACAO DO AMBIENTE =====",
        )

        if not cfg.codigo_central.is_file():
            registrar(f"ERRO: nao encontrei {cfg.codigo_central}.")
            execucao["mensagem"] = "codigo_central.py não encontrado."
            return 1

        env = os.environ.copy()
        env.update({
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "NOME_RESPONSAVEL": execucao["responsavel"],
            "GN_EXEC_USER": usuario_sistema,
            "GN_EXEC_COMPUTER": computador,
            "GN_EXEC_STARTED_AT": execucao["inicio"],
        })

        if self._rodar([cfg.python, "-c", IMPORTS_PROCESSO], cfg.comece_aqui, env, log) != 0:
            registrar("ERRO: bibliotecas do processo ausentes. Instale processo_im/1_Processo_Extracao_Dados/"
                      "Comece_aqui/Fonte_Dados/requirements.txt (no Docker elas ja vem na imagem).")
            execucao["mensagem"] = "Bibliotecas do processo de extração ausentes."
            return 1
        registrar("Dependencias carregadas com sucesso.")

        # Cegás, Copergás, MSGás e MTGás usam navegador headless (Selenium).
        navegador = env.get("GN_CHROME_BINARY") or next(filter(None, map(shutil.which, NAVEGADORES)), None)
        if navegador:
            env["GN_CHROME_BINARY"] = navegador
            registrar(f"Navegador para Selenium: {navegador}")
        else:
            registrar("AVISO: Chrome/Chromium nao encontrado. Os extratores CE (Cegas), PE (Copergas), "
                      "MS (MSGas) e MT (MTGas) podem falhar.")

        # ------------------------------------------------ etapa 1: extração e consolidação
        execucao["etapa"] = "extração"
        self._salvar_no_historico(execucao)
        registrar("", "===== SAIDA DO CODIGO =====")
        args = [cfg.python, str(cfg.codigo_central.relative_to(cfg.comece_aqui))]
        if opcoes["ufs"]:
            args += ["--only", opcoes["ufs"]]
        if opcoes["skip_run"]:
            args.append("--skip-run")
        status = self._rodar(args, cfg.comece_aqui, env, log, ao_ler=lambda linha: self._acompanhar_uf(execucao, linha))
        self._salvar_no_historico(execucao)

        # ------------------------------------------------ etapa 2: base da calculadora
        if status != 0 and not opcoes["mesmo_com_erro"]:
            registrar("", "Base da calculadora NAO foi atualizada porque houve erro na extracao.",
                      "Confira o log; para atualizar assim mesmo, rode novamente marcando "
                      "'atualizar a calculadora mesmo com erro'.")
            execucao["mensagem"] = "Houve erro na extração; a calculadora continua com a base anterior."
            return status

        execucao["etapa"] = "base da calculadora"
        self._salvar_no_historico(execucao)
        registrar("", "===== ATUALIZACAO DA CALCULADORA =====")
        cfg.saida_dir.mkdir(parents=True, exist_ok=True)
        saida_json = cfg.saida_dir / "tarifas.json"
        saida_js = cfg.saida_dir / "tarifas.js"
        saida_json.unlink(missing_ok=True)
        status_calc = self._rodar(
            [cfg.python, str(WRAPPER_ATUALIZAR), str(cfg.manutencao_dir), str(saida_json), str(saida_js)],
            cfg.manutencao_dir, env, log,
        )
        if status_calc != 0:
            registrar("ERRO: falha ao atualizar a base da calculadora.")
            execucao["mensagem"] = "Falha no atualizar_calculadora.py; a calculadora continua com a base anterior."
            return status_calc

        # ------------------------------------------------ etapa 3: validação e publicação
        execucao["etapa"] = "publicação"
        registrar("", "===== PUBLICACAO NA CALCULADORA =====")
        try:
            base = carregar_base(saida_json)
        except TarifasInvalidas as exc:
            registrar("ERRO: a base gerada nao passou na validacao. A calculadora continua com a base anterior.",
                      str(exc))
            execucao["mensagem"] = "Base gerada reprovada na validação; a calculadora continua com a anterior."
            return 1

        cfg.tarifas_json.parent.mkdir(parents=True, exist_ok=True)
        temporario = cfg.tarifas_json.with_suffix(".json.tmp")
        shutil.copyfile(saida_json, temporario)
        temporario.replace(cfg.tarifas_json)  # troca atômica: o servidor nunca lê arquivo pela metade
        execucao.update(base_publicada=True, registros=len(base.records), generated_at=base.generated_at)
        registrar(f"Base validada e publicada: {len(base.records)} registros (gerada em {base.generated_at}).",
                  f"Arquivo: {cfg.tarifas_json}")
        if status != 0:
            execucao["mensagem"] = "Base publicada, mas algum extrator falhou (UFs com dados anteriores)."
        else:
            execucao["mensagem"] = "Base da calculadora atualizada com sucesso."
        return status

    @staticmethod
    def _rodar(args: list[str], cwd: Path, env: dict, log, ao_ler=None) -> int:
        """Roda um comando, copiando a saída para o log linha a linha (como o tee do .sh)."""
        processo = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert processo.stdout is not None
        for linha in processo.stdout:
            log.write(linha)
            log.flush()
            sys.stdout.write(linha)
            if ao_ler:
                ao_ler(linha.rstrip("\r\n"))
        return processo.wait()

    @staticmethod
    def _acompanhar_uf(execucao: dict, linha: str) -> None:
        # O codigo_central.py imprime "Rodando SP..." seguido de "Status: ok" para cada extrator.
        if m := RE_RODANDO.match(linha):
            execucao["ufs"].append({"uf": m.group(1), "status": "rodando"})
        elif (m := RE_STATUS_UF.match(linha)) and execucao["ufs"] and execucao["ufs"][-1]["status"] == "rodando":
            execucao["ufs"][-1]["status"] = m.group(1).strip()

    # ------------------------------------------------------------------ histórico
    def _salvar_no_historico(self, execucao: dict) -> None:
        with self._lock_historico:
            historico = [h for h in self.historico() if h.get("log") != execucao["log"]]
            historico.insert(0, json.loads(json.dumps(execucao)))
            _gravar_json(self.config.historico_json, historico[:LIMITE_HISTORICO])

    def _marcar_interrompidas(self) -> None:
        """Execuções que estavam 'em execução' quando o servidor caiu não vão terminar."""
        with self._lock_historico:
            historico = self.historico()
            alterou = False
            for h in historico:
                if h.get("status") == "em execução":
                    h.update(status="interrompida", fim=h.get("fim") or "",
                             mensagem="O servidor foi reiniciado durante a execução.")
                    alterou = True
            if alterou:
                _gravar_json(self.config.historico_json, historico)
