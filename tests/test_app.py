import json

import pytest

from app import create_app, ler_volume
from calculadora.calculo import MSG_FORA_DAS_FAIXAS, MSG_SEM_TARIFA, ResultadoCalculo, calcular
from calculadora.dados import TarifasInvalidas, carregar_base, validar_registros
from calculadora.formatacao import moeda, numero


def registro(**extra):
    base = {
        "uf": "SP", "segmento_copa": "INDUSTRIAL", "concessionaria": "TESTE", "segmento": "Industrial",
        "preco_concessionaria": "sem impostos", "faixa_min": 0.0, "faixa_max": 1000.0, "tarifa": 2.0,
        "termo_fixo": 100.0, "pis_cofins": 0.0925, "icms": 0.18, "ordem": 1.0, "cascata": False,
    }
    base.update(extra)
    return base


@pytest.fixture
def base_teste(tmp_path):
    caminho = tmp_path / "tarifas.json"
    caminho.write_text(json.dumps({"generated_at": "teste", "records": [
        registro(),
        registro(faixa_min=1000.01, faixa_max=99999999999.0, tarifa=1.5, termo_fixo=300.0, ordem=2.0),
        registro(segmento_copa="CONDOMINIOS", concessionaria="<script>x</script>", cascata=True, termo_fixo=0.0),
    ]}), encoding="utf-8")
    return caminho


@pytest.fixture
def cliente(base_teste):
    return create_app(base_teste).test_client()


# ------------------------------------------------------------------ formatação

@pytest.mark.parametrize("valor, esperado", [
    (0, "0"), (1234.5, "1.234,5"), (1.005, "1,01"), (1234.005, "1.234,01"),
    (99999999999.0, "99.999.999.999"), (-23.171, "-23,17"), (0.004, "0"), (-0.0, "-0"),
])
def test_numero_como_intl(valor, esperado):
    assert numero(valor) == esperado


def test_moeda_como_intl():
    assert moeda(1234.5) == "R$ 1.234,50"
    assert moeda(-1234.565) == "-R$ 1.234,57"


# ------------------------------------------------------------------ validação

def test_validacao_aponta_problemas():
    erros = validar_registros([registro(tarifa=None), registro(icms=18), registro(faixa_min=10, faixa_max=5), registro(cascata="sim")])
    assert len(erros) == 4
    assert validar_registros([]) == ["Nenhum registro de tarifa encontrado."]
    assert validar_registros([registro(tarifa=True)])  # booleano não é número


def test_base_invalida_bloqueia_calculadora(tmp_path):
    caminho = tmp_path / "tarifas.json"
    caminho.write_text(json.dumps({"records": [registro(tarifa="abc")]}), encoding="utf-8")
    with pytest.raises(TarifasInvalidas):
        carregar_base(caminho)
    resposta = create_app(caminho).test_client().get("/")
    assert resposta.status_code == 503
    assert "Base tarifária indisponível" in resposta.get_data(as_text=True)


def test_recarga_troca_a_base(base_teste, cliente):
    assert cliente.get("/saude").get_json()["registros"] == 3
    base_teste.write_text(json.dumps({"generated_at": "novo", "records": [registro()]}), encoding="utf-8")
    assert cliente.application.extensions["tarifas"].recarregar()
    saude = cliente.get("/saude").get_json()
    assert (saude["status"], saude["registros"], saude["generated_at"], saude["origem"]) == ("ok", 1, "novo", "json")


def test_saude_e_pronto(base_teste, tmp_path):
    assert create_app(base_teste).test_client().get("/saude/pronto").status_code == 200
    sem_base = create_app(tmp_path / "nao_existe.json").test_client()
    # Liveness responde mesmo sem base; readiness não.
    assert sem_base.get("/saude").status_code == 200
    assert sem_base.get("/saude").get_json()["status"] == "sem_base"
    assert sem_base.get("/saude/pronto").status_code == 503


# ------------------------------------------------------------------ cálculo

def test_sem_cascata_com_termo_fixo(base_teste):
    records = carregar_base(base_teste).records
    r = calcular(records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "gn", 500)
    assert isinstance(r, ResultadoCalculo) and not r.cascata
    assert r.fatura_liquida == pytest.approx(500 * 2.0 + 100)
    # PIS/Cofins por dentro, depois ICMS por dentro
    com_pis = 1100 / (1 - 0.0925)
    assert r.total_pis_cofins == pytest.approx(com_pis - 1100)
    assert r.fatura_bruta_gn == pytest.approx(com_pis / (1 - 0.18))


def test_cascata_soma_termo_fixo_da_ultima_classe(tmp_path):
    """B-03 (ADR 0005): na cascata entra o termo fixo da última Classe atingida, não o das anteriores."""
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps({"records": [
        registro(cascata=True, faixa_min=0.0, faixa_max=100.0, tarifa=3.0, termo_fixo=10.0),
        registro(cascata=True, faixa_min=100.0, faixa_max=99999999999.0, tarifa=2.0, termo_fixo=50.0, ordem=2.0),
    ]}), encoding="utf-8")
    records = carregar_base(caminho).records
    r = calcular(records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "gn", 250)
    assert r.termo_fixo == 50.0
    assert [f.termo_fixo for f in r.faixas] == [0, 50.0]
    assert r.fatura_liquida == pytest.approx(100 * 3 + 150 * 2 + 50)
    com_pis = (150 * 2 + 50) / (1 - 0.0925)
    assert r.faixas[-1].fatura_bruta == pytest.approx(com_pis / (1 - 0.18))
    # Volume só na 1ª Classe: vale o termo fixo dela.
    assert calcular(records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "gn", 40).fatura_liquida == pytest.approx(40 * 3 + 10)


def test_cascata_com_termo_fixo_mostra_a_coluna(tmp_path):
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps({"records": [
        registro(cascata=True, faixa_min=0.0, faixa_max=99999999999.0, tarifa=2.0, termo_fixo=50.0),
        registro(uf="RJ", cascata=True, faixa_min=0.0, faixa_max=99999999999.0, tarifa=2.0, termo_fixo=0.0),
    ]}), encoding="utf-8")
    cliente = create_app(caminho).test_client()
    filtros = {"segmento_copa": "INDUSTRIAL", "tipo_entrada": "gn", "volume": "10"}
    html = cliente.get("/api/calcular", query_string={"uf": "SP", **filtros}).get_json()["html"]
    assert '<th id="termoFixoHeader">' in html
    html = cliente.get("/api/calcular", query_string={"uf": "RJ", **filtros}).get_json()["html"]
    assert '<th id="termoFixoHeader" hidden>' in html


def test_fatores_da_gold_substituem_as_constantes(tmp_path):
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps({"records": [registro()],
                                   "parametros": {"FATOR_GN_PARA_GLP": 0.5, "FATOR_GLP_PARA_GN": 2.0}}), encoding="utf-8")
    base = carregar_base(caminho)
    r = calcular(base.records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "glp", 100, parametros=base.parametros)
    assert r.volume_gn == 200.0
    r = calcular(base.records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "gn", 100, parametros=base.parametros)
    assert r.volume_glp == 50.0
    html = create_app(caminho).test_client().get("/", query_string={"segmento_copa": "INDUSTRIAL"}).get_data(as_text=True)
    assert "GLP para GN = * 2;" in html


def test_monofasica_da_gold(tmp_path):
    caminho = tmp_path / "t.json"
    parametros = {"FATOR_GN_PARA_GLP": 0.826087, "FATOR_GLP_PARA_GN": 1.210526, "ALIQUOTA_MONOFASICA_GLP": 2.0}
    caminho.write_text(json.dumps({"records": [registro()], "parametros": parametros}), encoding="utf-8")
    base = carregar_base(caminho)
    r = calcular(base.records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "glp", 100, parametros=base.parametros)
    assert r.tarifa_bruta_unitaria_glp == pytest.approx(r.tarifa_liquida_unitaria_glp + 2.0)
    r = calcular(base.records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "glp", 100)  # sem parâmetros: constante
    assert r.tarifa_bruta_unitaria_glp == pytest.approx(r.tarifa_liquida_unitaria_glp + 1.6377)


def test_com_cascata_distribui_nas_faixas(tmp_path):
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps({"records": [
        registro(cascata=True, faixa_min=0.0, faixa_max=100.0, tarifa=3.0, termo_fixo=0.0),
        registro(cascata=True, faixa_min=100.0, faixa_max=99999999999.0, tarifa=2.0, termo_fixo=0.0, ordem=2.0),
    ]}), encoding="utf-8")
    r = calcular(carregar_base(caminho).records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "gn", 250)
    assert [f.consumo for f in r.faixas] == [100, 150]
    assert r.fatura_liquida == pytest.approx(100 * 3 + 150 * 2)


def test_conversao_glp_gn(base_teste):
    r = calcular(carregar_base(base_teste).records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "glp", 100)
    assert r.volume_glp == 100 and r.volume_gn == pytest.approx(121.0526)


@pytest.mark.parametrize("volume, mensagem", [(0, MSG_SEM_TARIFA), (-5, MSG_SEM_TARIFA)])
def test_volume_invalido(base_teste, volume, mensagem):
    r = calcular(carregar_base(base_teste).records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "gn", volume)
    assert r.mensagem == mensagem


def test_volume_fora_das_faixas(tmp_path):
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps({"records": [registro(faixa_min=10.0, faixa_max=20.0)]}), encoding="utf-8")
    r = calcular(carregar_base(caminho).records, "SP", "INDUSTRIAL", "TESTE", "Industrial", "gn", 5)
    assert r.mensagem == MSG_FORA_DAS_FAIXAS


@pytest.mark.parametrize("texto, esperado", [(None, 5000.0), ("", 0.0), ("abc", 0.0), ("inf", 0.0), ("nan", 0.0), ("1,5", 1.5), (" 20 ", 20.0)])
def test_ler_volume(texto, esperado):
    assert ler_volume(texto) == esperado


# ------------------------------------------------------------------ rotas

def test_pagina_inicial_renderiza_calculo(cliente):
    html = cliente.get("/").get_data(as_text=True)  # padrão: primeiro segmento (CONDOMINIOS)
    assert "Cálculo automático" in html
    assert 'id="comparisonCreditoPanel" class="panel comparison-panel" hidden>' in html
    html = cliente.get("/", query_string={"segmento_copa": "INDUSTRIAL"}).get_data(as_text=True)
    assert 'id="comparisonCreditoPanel" class="panel comparison-panel">' in html  # só industrial vê


def test_api_calcular(cliente):
    dados = cliente.get("/api/calcular", query_string={"uf": "SP", "segmento_copa": "INDUSTRIAL", "tipo_entrada": "gn", "volume": "2000"}).get_json()
    assert dados["filtros"]["segmento_copa"]["selecionado"] == "INDUSTRIAL"
    assert dados["resultado"]["ok"] is True
    assert dados["resultado"]["faixas"][0]["faixa_min"] == 1000.01
    assert 'id="resultados"' in dados["html"]


def test_parametros_invalidos_nao_quebram(cliente):
    dados = cliente.get("/api/calcular", query_string={"uf": "ZZ", "tipo_entrada": "xpto", "volume": "abc"}).get_json()
    assert dados["filtros"]["uf"]["selecionado"] == "SP"
    assert dados["resultado"] == {"ok": False, "mensagem": MSG_SEM_TARIFA}


def test_situacao_da_tarifa_na_tela(tmp_path):
    caminho = tmp_path / "t.json"
    caminho.write_text(json.dumps({"records": [
        registro(atualizado_em="2026-10-29", vigencia_inicio="2026-10-01", status_atualizacao="atualizada",
                 origem_valor="execucao_atual"),
        registro(uf="AM", atualizado_em=None, vigencia_inicio=None, status_atualizacao="desatualizada",
                 origem_valor="base_manual"),
        registro(uf="PR", atualizado_em="2026-09-01", status_atualizacao="desatualizada",
                 origem_valor="anterior_tabela_ausente"),
        registro(uf="RJ", atualizado_em="2026-10-29", deliberacao="AGENERSA 5.123/2026"),
    ]}), encoding="utf-8")
    cliente = create_app(caminho).test_client()

    def situacao(uf):
        html = cliente.get("/api/calcular", query_string={"uf": uf, "segmento_copa": "INDUSTRIAL"}).get_json()["html"]
        return " ".join(html.split('id="situacaoTarifa">')[1].split("</p>")[0].split())

    assert situacao("SP") == "<b>Tarifa atualizada em:</b> 29/10/2026 · <b>Vigente desde:</b> 01/10/2026"
    assert "base manual" in situacao("AM")
    assert "mantido o último valor válido" in situacao("PR")
    assert situacao("RJ") == "<b>Tarifa atualizada em:</b> 29/10/2026 · <b>Deliberação:</b> AGENERSA 5.123/2026"


def test_validacao_dos_campos_novos_da_gold():
    assert validar_registros([registro(status_atualizacao="atualizada", origem_valor="base_manual",
                                       atualizado_em=None, vigencia_inicio="2026-10-01")]) == []
    erros = validar_registros([registro(status_atualizacao="velha", origem_valor="xpto", atualizado_em=20261001)])
    assert len(erros) == 3


def test_texto_da_base_e_escapado(cliente):
    html = cliente.get("/", query_string={"segmento_copa": "CONDOMINIOS"}).get_data(as_text=True)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html


def test_mapa_e_retorno(cliente):
    assert cliente.get("/mapa/").status_code in (200, 404)
    assert cliente.get("/mapa/../app.py").status_code == 404
    assert cliente.get("/5_Calculadora_Final/index.html").status_code == 302
