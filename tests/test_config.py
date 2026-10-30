"""Testes da configuração por variáveis de ambiente."""

from __future__ import annotations

from pathlib import Path

import pytest

from calculadora.config import Config, ConfigInvalida, carregar_config

DATABRICKS = {"DATABRICKS_HOST": "https://exemplo.invalido/", "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/x"}


def _env(**extra) -> dict:
    return {**DATABRICKS, "DATABRICKS_TOKEN": "tok-ficticio", **extra}


def test_padroes_em_dev_com_pat():
    cfg = carregar_config(_env())
    assert cfg.ambiente == "dev"
    assert cfg.fonte == "databricks"
    assert cfg.tabela_completa == "marketing_dev.dbt_guilherme_oliveira.fct_gn_tarifa_vigente_calculadora"
    assert cfg.auth_tipo == "pat"
    assert (cfg.recarga_minutos, cfg.timeout_consulta_s, cfg.base_max_idade_horas) == (30, 60, 72)
    assert cfg.cache_path == Path("./.cache/tarifas.json")


@pytest.mark.parametrize(
    "ambiente, esperado",
    [
        ("dev", "marketing_dev.dbt_guilherme_oliveira"),
        ("hml", "marketing_hml.marketing_gold"),
        ("prd", "marketing_prd.marketing_gold"),
    ],
)
def test_resolve_catalogo_e_schema_pelo_ambiente(ambiente, esperado):
    env = _env(GN_AMBIENTE=ambiente, GN_AUTH_TIPO="pat")
    cfg = carregar_config(env)
    assert f"{cfg.catalogo}.{cfg.schema}" == esperado


def test_override_de_catalogo_e_schema():
    cfg = carregar_config(_env(GN_CATALOGO="outro_cat", GN_SCHEMA="outro_sch", GN_TABELA_TARIFAS="outra",
                               GN_TABELA_PARAMETROS="outros_parametros"))
    assert cfg.tabela_completa == "outro_cat.outro_sch.outra"
    assert cfg.tabela_parametros_completa == "outro_cat.outro_sch.outros_parametros"


def test_tabela_de_parametros_padrao():
    cfg = carregar_config(_env(GN_AMBIENTE="prd", GN_AUTH_TIPO="pat"))
    assert cfg.tabela_parametros_completa == "marketing_prd.marketing_gold.fct_gn_parametro_vigente_calculadora"


def test_hml_e_prd_usam_oauth_m2m_por_padrao():
    env = {**DATABRICKS, "GN_AMBIENTE": "hml", "DATABRICKS_CLIENT_ID": "id", "DATABRICKS_CLIENT_SECRET": "s"}
    assert carregar_config(env).auth_tipo == "oauth_m2m"


def test_host_aceita_https_e_barra_final():
    assert carregar_config(_env()).databricks_host == "exemplo.invalido"


def test_variaveis_ausentes_sao_todas_reportadas():
    with pytest.raises(ConfigInvalida) as erro:
        carregar_config({})
    texto = str(erro.value)
    assert "DATABRICKS_HOST é obrigatória" in texto
    assert "DATABRICKS_HTTP_PATH é obrigatória" in texto
    assert "DATABRICKS_TOKEN é obrigatória quando GN_AUTH_TIPO=pat" in texto


def test_pat_sem_token_e_m2m_sem_credenciais():
    with pytest.raises(ConfigInvalida, match="DATABRICKS_TOKEN"):
        carregar_config(dict(DATABRICKS))
    with pytest.raises(ConfigInvalida) as erro:
        carregar_config({**DATABRICKS, "GN_AUTH_TIPO": "oauth_m2m"})
    assert "DATABRICKS_CLIENT_ID" in str(erro.value) and "DATABRICKS_CLIENT_SECRET" in str(erro.value)


def test_u2m_nao_exige_segredo():
    assert carregar_config({**DATABRICKS, "GN_AUTH_TIPO": "oauth_u2m"}).auth_tipo == "oauth_u2m"


@pytest.mark.parametrize(
    "variavel, valor",
    [
        ("GN_AMBIENTE", "producao"),
        ("GN_FONTE", "csv"),
        ("GN_AUTH_TIPO", "senha"),
        ("GN_RECARGA_MINUTOS", "abc"),
        ("GN_RECARGA_MINUTOS", "0"),
        ("GN_TIMEOUT_CONSULTA_S", "-5"),
        ("GN_BASE_MAX_IDADE_HORAS", "1.5"),
    ],
)
def test_valores_invalidos_apontam_a_variavel(variavel, valor):
    with pytest.raises(ConfigInvalida, match=variavel):
        carregar_config(_env(**{variavel: valor}))


@pytest.mark.parametrize("variavel", ["GN_CATALOGO", "GN_SCHEMA", "GN_TABELA_TARIFAS", "GN_TABELA_PARAMETROS"])
def test_identificadores_com_caracteres_perigosos_sao_recusados(variavel):
    with pytest.raises(ConfigInvalida, match=variavel):
        carregar_config(_env(**{variavel: "x; DROP TABLE t"}))


def test_fonte_json_exige_arquivo_e_nao_exige_databricks():
    with pytest.raises(ConfigInvalida, match="GN_ARQUIVO_JSON"):
        carregar_config({"GN_FONTE": "json"})
    cfg = carregar_config({"GN_FONTE": "json", "GN_ARQUIVO_JSON": "tests/fixtures/tarifas_2026-09-03.json"})
    assert cfg.arquivo_json == Path("tests/fixtures/tarifas_2026-09-03.json")


def test_segredos_nao_aparecem_em_repr_nem_resumo():
    cfg = carregar_config(
        _env(GN_AUTH_TIPO="oauth_m2m", DATABRICKS_CLIENT_ID="id-ficticio", DATABRICKS_CLIENT_SECRET="seg-ficticio")
    )
    exposto = repr(cfg) + str(cfg.resumo())
    for segredo in ("tok-ficticio", "id-ficticio", "seg-ficticio", "exemplo.invalido"):
        assert segredo not in exposto
    assert isinstance(cfg, Config)


def test_le_do_ambiente_do_processo(monkeypatch):
    for chave, valor in _env(GN_AMBIENTE="hml", GN_AUTH_TIPO="pat").items():
        monkeypatch.setenv(chave, valor)
    assert carregar_config().ambiente == "hml"
