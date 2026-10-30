"""Cenários do repositório com fonte falsa (seção 6.3 do plano)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from calculadora import cache_local
from calculadora.dados import RepositorioTarifas, TarifasInvalidas


def registro(**extra):
    base = {
        "uf": "SP", "segmento_copa": "INDUSTRIAL", "concessionaria": "TESTE", "segmento": "Industrial",
        "preco_concessionaria": "sem impostos", "faixa_min": 0.0, "faixa_max": 99999999999.0, "tarifa": 2.0,
        "termo_fixo": 0.0, "pis_cofins": 0.0925, "icms": 0.18, "ordem": 1, "cascata": False,
    }
    base.update(extra)
    return base


def payload(n=1, **extra):
    return {"generated_at": "2026-10-29", "source": "teste", "records": [registro(**extra) for _ in range(n)],
            "parametros": {"FATOR_GN_PARA_GLP": 0.826087, "FATOR_GLP_PARA_GN": 1.210526}}


class FonteFalsa:
    origem = "databricks"

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = 0

    def carregar(self):
        self.chamadas += 1
        resposta = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class Relogio:
    def __init__(self):
        self.agora = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.agora


def test_carga_ok_grava_copia(tmp_path):
    cache = tmp_path / "cache" / "tarifas.json"
    repo = RepositorioTarifas(FonteFalsa(payload(3)), cache_path=cache)
    assert repo.recarregar()
    assert repo.obter().origem == "databricks" and len(repo.obter().records) == 3
    assert repo.estado()["status"] == "ok"
    assert cache_local.ler(cache)["payload"]["records"][0]["uf"] == "SP"


def test_databricks_fora_usa_copia_local(tmp_path):
    cache = tmp_path / "tarifas.json"
    RepositorioTarifas(FonteFalsa(payload(2)), cache_path=cache).recarregar()

    repo = RepositorioTarifas(FonteFalsa(ConnectionError("sem rede")), cache_path=cache)
    assert repo.carregar_cache()
    assert not repo.recarregar()
    assert repo.obter().origem == "cache_local"
    estado = repo.estado()
    assert estado["status"] == "degradado"
    assert "sem rede" in estado["ultimo_erro"]


def test_sem_databricks_e_sem_copia_da_503(tmp_path):
    repo = RepositorioTarifas(FonteFalsa(ConnectionError("sem rede")), cache_path=tmp_path / "nao_existe.json")
    assert not repo.carregar_cache()
    assert not repo.recarregar()
    with pytest.raises(TarifasInvalidas, match="sem rede"):
        repo.obter()
    cliente = create_app(FonteFalsa(ConnectionError("sem rede"))).test_client()
    assert cliente.get("/").status_code == 503
    assert cliente.get("/saude/pronto").status_code == 503


def test_recarga_invalida_mantem_a_ultima_valida():
    fonte = FonteFalsa(payload(2), payload(1, tarifa="abc"))
    repo = RepositorioTarifas(fonte)
    assert repo.recarregar()
    assert not repo.recarregar()
    assert len(repo.obter().records) == 2
    assert "inválida" in repo.estado()["ultimo_erro"]


def test_gold_sem_parametros_e_invalida():
    sem_fator = payload(1)
    del sem_fator["parametros"]["FATOR_GLP_PARA_GN"]
    repo = RepositorioTarifas(FonteFalsa(sem_fator))
    assert not repo.recarregar()
    assert "FATOR_GLP_PARA_GN" in repo.estado()["ultimo_erro"]


def test_recarga_atualiza_a_base():
    repo = RepositorioTarifas(FonteFalsa(payload(1), payload(4)))
    repo.recarregar()
    repo.recarregar()
    assert len(repo.obter().records) == 4


def test_base_antiga_gera_aviso(tmp_path):
    relogio = Relogio()
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps(payload(1)), encoding="utf-8")
    repo = RepositorioTarifas(FonteFalsa(payload(1)), max_idade_horas=72, relogio=relogio)
    repo.recarregar()
    assert not repo.base_antiga()
    relogio.agora += timedelta(hours=73)
    assert repo.base_antiga()
    assert repo.estado()["status"] == "degradado"

    app = create_app(caminho)
    app.extensions["tarifas"]._relogio = lambda: datetime.now(timezone.utc) + timedelta(hours=100)
    html = app.test_client().get("/").get_data(as_text=True)
    assert "a base tarifária não é atualizada desde" in html


def test_copia_local_atomica_e_tolerante(tmp_path):
    cache = tmp_path / "tarifas.json"
    cache_local.gravar(cache, payload(1), "databricks", "2026-10-30T12:00:00+00:00")
    assert [p.name for p in tmp_path.iterdir()] == ["tarifas.json"]  # sem temporário esquecido
    cache.write_text('{"payload": {"records": [', encoding="utf-8")  # arquivo truncado
    assert cache_local.ler(cache) is None
    assert cache_local.ler(tmp_path / "nao_existe.json") is None


def test_copia_local_invalida_e_ignorada(tmp_path):
    cache = tmp_path / "tarifas.json"
    cache_local.gravar(cache, payload(1, tarifa=-1), "databricks", "2026-10-30T12:00:00+00:00")
    repo = RepositorioTarifas(FonteFalsa(ConnectionError("x")), cache_path=cache)
    assert not repo.carregar_cache()


def test_iniciar_carrega_em_segundo_plano(tmp_path):
    fonte = FonteFalsa(payload(2))
    repo = RepositorioTarifas(fonte, recarga_minutos=30)
    repo.iniciar()
    repo._thread.join(timeout=0.5)  # a thread fica no laço de espera depois da 1ª carga
    try:
        assert fonte.chamadas == 1
        assert len(repo.obter().records) == 2
    finally:
        repo.parar()
