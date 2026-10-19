"""ETL: orquestração do processo do IM, agendamento e tela /interno/etl.

Usa um processo falso com a mesma estrutura de pastas do IM, para não acessar os sites.
"""

import base64
import json
import sys
import textwrap
import time
from datetime import datetime

import pytest

import etl.executor
from app import create_app
from etl import Agendador, ConfiguracaoEtl, EtlEmExecucao, ExecutorEtl
from etl.agendamento import (AGENDAMENTO_PADRAO, AgendamentoInvalido, carregar_agendamento, proxima_execucao,
                             salvar_agendamento)

REGISTRO = {
    "uf": "SP", "segmento_copa": "INDUSTRIAL", "concessionaria": "TESTE", "segmento": "Industrial",
    "preco_concessionaria": "sem impostos", "faixa_min": 0.0, "faixa_max": 1000.0, "tarifa": 2.0,
    "termo_fixo": 100.0, "pis_cofins": 0.0925, "icms": 0.18, "ordem": 1.0, "cascata": False,
}

CODIGO_CENTRAL_FALSO = """
import os, sys
print("Extratores selecionados: SP, RJ")
print("argv:", " ".join(sys.argv[1:]))
print("responsavel:", os.environ.get("NOME_RESPONSAVEL"))
print("\\nRodando SP...")
print("Status: ok")
print("\\nRodando RJ...")
print("Status: " + ("erro ao executar" if os.environ.get("FALSO_FALHA") else "ok"))
sys.exit(1 if os.environ.get("FALSO_FALHA") else 0)
"""

ATUALIZAR_FALSO = """
import json, os
from pathlib import Path
OUTPUT_TARIFFS_JS = Path("nao-usar.js")
OUTPUT_TARIFFS_JSON = Path("nao-usar.json")
def main():
    registro = json.loads(os.environ["FALSO_REGISTRO"])
    payload = {"generated_at": "2026-10-19 00:00:01", "records": [registro]}
    OUTPUT_TARIFFS_JS.write_text("window.TARIFAS_GN = " + json.dumps(payload) + ";", encoding="utf-8")
    OUTPUT_TARIFFS_JSON.write_text(json.dumps(payload), encoding="utf-8")
    print("Registros finais no tarifas.js: 1")
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(etl.executor, "IMPORTS_PROCESSO", "import json")
    monkeypatch.setenv("FALSO_REGISTRO", json.dumps(REGISTRO))
    monkeypatch.delenv("FALSO_FALHA", raising=False)
    processo = tmp_path / "processo_im"
    fonte = processo / "1_Processo_Extracao_Dados" / "Comece_aqui" / "Fonte_Dados"
    fonte.mkdir(parents=True)
    (fonte / "codigo_central.py").write_text(textwrap.dedent(CODIGO_CENTRAL_FALSO), encoding="utf-8")
    (processo / "3_Manutencao").mkdir()
    (processo / "3_Manutencao" / "atualizar_calculadora.py").write_text(textwrap.dedent(ATUALIZAR_FALSO), encoding="utf-8")

    tarifas = tmp_path / "data" / "tarifas.json"
    tarifas.parent.mkdir()
    tarifas.write_text(json.dumps({"generated_at": "base anterior", "records": [dict(REGISTRO, tarifa=9.0)]}), encoding="utf-8")
    return ConfiguracaoEtl(processo_dir=processo, tarifas_json=tarifas, estado_dir=tmp_path / "data" / "etl",
                           python=sys.executable)


def base_publicada(config):
    return json.loads(config.tarifas_json.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ executor

def test_execucao_com_sucesso_publica_a_base(config):
    executor = ExecutorEtl(config)
    execucao = executor.executar(origem="manual", responsavel="Maria Silva", ufs="sp, rj")

    assert execucao["status"] == "sucesso"
    assert execucao["base_publicada"] and execucao["registros"] == 1
    assert execucao["ufs"] == [{"uf": "SP", "status": "ok"}, {"uf": "RJ", "status": "ok"}]
    assert base_publicada(config)["generated_at"] == "2026-10-19 00:00:01"

    hoje = datetime.now().strftime("%Y-%m-%d")
    assert execucao["log"] == f"Execucao_001_{hoje}_Maria_Silva.log"
    log = (config.log_dir / execucao["log"]).read_text(encoding="utf-8")
    assert "argv: --only SP,RJ" in log
    assert "responsavel: Maria Silva" in log
    assert "===== PUBLICACAO NA CALCULADORA =====" in log
    assert log.rstrip().endswith("Status: 0")

    assert executor.historico()[0]["status"] == "sucesso"
    assert executor.em_execucao() is None
    assert executor.executar(origem="manual", responsavel="Maria Silva")["log"].startswith("Execucao_002_")


def test_falha_na_extracao_mantem_a_base_anterior(config, monkeypatch):
    monkeypatch.setenv("FALSO_FALHA", "1")
    execucao = ExecutorEtl(config).executar(origem="agendamento", responsavel="Agendamento")

    assert execucao["status"] == "erro"
    assert not execucao["base_publicada"]
    assert execucao["ufs"][1] == {"uf": "RJ", "status": "erro ao executar"}
    assert base_publicada(config)["generated_at"] == "base anterior"
    assert "NAO foi atualizada" in (config.log_dir / execucao["log"]).read_text(encoding="utf-8")


def test_mesmo_com_erro_publica_como_parcial(config, monkeypatch):
    monkeypatch.setenv("FALSO_FALHA", "1")
    execucao = ExecutorEtl(config).executar(origem="manual", responsavel="x", mesmo_com_erro=True)
    assert execucao["status"] == "parcial"
    assert base_publicada(config)["generated_at"] == "2026-10-19 00:00:01"


def test_base_invalida_nao_e_publicada(config, monkeypatch):
    monkeypatch.setenv("FALSO_REGISTRO", json.dumps(dict(REGISTRO, icms=18)))  # alíquota fora de 0–1
    execucao = ExecutorEtl(config).executar(origem="manual", responsavel="x")
    assert execucao["status"] == "erro"
    assert "validação" in execucao["mensagem"]
    assert base_publicada(config)["generated_at"] == "base anterior"


def test_uma_execucao_por_vez(config):
    executor = ExecutorEtl(config)
    executor._reservar("manual", "x", "", False, False)
    with pytest.raises(EtlEmExecucao):
        executor.iniciar(origem="manual", responsavel="y")


def test_execucao_interrompida_por_reinicio(config):
    ExecutorEtl(config)._reservar("manual", "x", "", False, False)
    assert ExecutorEtl(config).historico()[0]["status"] == "interrompida"


def test_nome_de_log_nao_sai_da_pasta(config):
    executor = ExecutorEtl(config)
    assert executor.caminho_log("../tarifas.json") is None
    assert executor.caminho_log("Execucao_001_2026-01-01_x.log") is None  # não existe


# ------------------------------------------------------------------ agendamento

def test_agendamento_padrao_e_meia_noite(tmp_path):
    assert carregar_agendamento(tmp_path / "nao_existe.json") == AGENDAMENTO_PADRAO
    assert AGENDAMENTO_PADRAO["horario"] == "00:00" and AGENDAMENTO_PADRAO["dias"] == list(range(7))


def test_proxima_execucao():
    ag = {"ativo": True, "horario": "00:00", "dias": list(range(7))}
    assert proxima_execucao(ag, datetime(2026, 10, 19, 15, 0)) == datetime(2026, 10, 20, 0, 0)
    assert proxima_execucao(ag, datetime(2026, 10, 19, 23, 59, 59)) == datetime(2026, 10, 20, 0, 0)
    assert proxima_execucao(ag, datetime(2026, 10, 20, 0, 0)) == datetime(2026, 10, 21, 0, 0)
    # 19/10/2026 é segunda; só sábado (5) às 06:30
    sabado = {"ativo": True, "horario": "06:30", "dias": [5]}
    assert proxima_execucao(sabado, datetime(2026, 10, 19, 12, 0)) == datetime(2026, 10, 24, 6, 30)
    assert proxima_execucao(dict(ag, ativo=False), datetime(2026, 10, 19)) is None


@pytest.mark.parametrize("dados", [
    {"ativo": True, "horario": "24:00", "dias": [0]},
    {"ativo": True, "horario": "7h", "dias": [0]},
    {"ativo": True, "horario": "07:00", "dias": [7]},
    {"ativo": True, "horario": "07:00", "dias": []},
])
def test_agendamento_invalido(tmp_path, dados):
    with pytest.raises(AgendamentoInvalido):
        salvar_agendamento(tmp_path / "ag.json", dados)


def test_agendador_dispara_no_horario(config):
    disparos = []

    class ExecutorFalso:
        def iniciar(self, **kwargs):
            disparos.append(kwargs)

    salvar_agendamento(config.agendamento_json, {"ativo": True, "horario": "00:00", "dias": list(range(7))})
    agendador = Agendador(ExecutorFalso(), config.agendamento_json)
    agendador._referencia = datetime(2026, 10, 19, 23, 59, 40)

    assert not agendador.verificar(datetime(2026, 10, 19, 23, 59, 50))
    assert agendador.verificar(datetime(2026, 10, 20, 0, 0, 10))
    assert not agendador.verificar(datetime(2026, 10, 20, 0, 0, 40))  # não repete no mesmo horário
    assert disparos == [{"origem": "agendamento", "responsavel": "Agendamento", "mesmo_com_erro": False}]


def test_alterar_agendamento_nao_dispara_horario_que_ja_passou(config):
    disparos = []

    class ExecutorFalso:
        def iniciar(self, **kwargs):
            disparos.append(kwargs)

    agendador = Agendador(ExecutorFalso(), config.agendamento_json)
    agendador._referencia = datetime(2026, 10, 19, 10, 0)
    time.sleep(0.01)
    salvar_agendamento(config.agendamento_json, {"ativo": True, "horario": "14:00", "dias": list(range(7))})
    assert not agendador.verificar(datetime(2026, 10, 19, 15, 0))  # alterado às 15h para 14h
    assert not agendador.verificar(datetime(2026, 10, 19, 15, 1))
    assert agendador.verificar(datetime(2026, 10, 20, 14, 0, 5))
    assert len(disparos) == 1


# ------------------------------------------------------------------ tela

@pytest.fixture
def cliente(config):
    return create_app(config.tarifas_json, config_etl=config).test_client()


def test_tela_oculta_responde(cliente):
    resposta = cliente.get("/interno/etl/")
    assert resposta.status_code == 200
    html = resposta.get_data(as_text=True)
    assert "ETL da base tarifária" in html and "Executar ETL" in html
    assert resposta.headers["X-Robots-Tag"] == "noindex, nofollow"
    assert "/interno/etl" not in cliente.get("/").get_data(as_text=True)  # sem link no site


def test_tela_com_senha(config):
    config = ConfiguracaoEtl(**{**config.__dict__, "senha": "s3nha"})
    cliente = create_app(config.tarifas_json, config_etl=config).test_client()
    assert cliente.get("/interno/etl/").status_code == 401
    errada = base64.b64encode(b"etl:outra").decode()
    assert cliente.get("/interno/etl/", headers={"Authorization": f"Basic {errada}"}).status_code == 401
    certa = base64.b64encode(b"etl:s3nha").decode()
    assert cliente.get("/interno/etl/", headers={"Authorization": f"Basic {certa}"}).status_code == 200
    assert cliente.get("/").status_code == 200  # a calculadora continua aberta


def test_executar_pela_tela_e_ler_log(cliente, config):
    resposta = cliente.post("/interno/etl/executar", data={"responsavel": "Tela", "ufs": "SP"})
    assert resposta.status_code == 302
    for _ in range(100):
        status = cliente.get("/interno/etl/status").get_json()
        if not status["em_execucao"]:
            break
        time.sleep(0.1)
    ultima = status["historico"][0]
    assert ultima["status"] == "sucesso" and ultima["origem"] == "manual"
    assert status["base"]["generated_at"] == "2026-10-19 00:00:01"  # a calculadora já usa a base nova

    log = cliente.get(f"/interno/etl/log/{ultima['log']}").get_json()
    assert "Responsavel: Tela" in log["texto"]
    continuacao = cliente.get(f"/interno/etl/log/{ultima['log']}?desde={log['tamanho']}").get_json()
    assert continuacao["texto"] == ""
    assert cliente.get("/interno/etl/log/..%2Ftarifas.json").status_code == 404


def test_salvar_agendamento_pela_tela(cliente, config):
    resposta = cliente.post("/interno/etl/agendamento", data={"ativo": "1", "horario": "06:30", "dias": ["0", "4"]})
    assert resposta.status_code == 302
    assert carregar_agendamento(config.agendamento_json) == {
        "ativo": True, "horario": "06:30", "dias": [0, 4], "mesmo_com_erro": False}
    assert "Seg, Sex às 06:30" in cliente.get("/interno/etl/").get_data(as_text=True)


def test_post_de_outro_site_e_recusado(cliente):
    resposta = cliente.post("/interno/etl/agendamento", data={"ativo": "1", "horario": "06:30", "dias": ["0"]},
                            headers={"Origin": "https://outro-site.example"})
    assert resposta.status_code == 403
