"""Garante que a versão Flask exibe exatamente o que o app.js original exibia.

Roda o app.js original (5_Calculadora_Final) em Node (DOM simulado) para
centenas de cenários — todas as combinações da base × volumes × GLP/GN — e
compara texto a texto com o HTML gerado pelo Python. A base é a fixture
congelada de 2026-09-03: a lógica de cálculo não muda com a fonte de dados,
então isso prova que a troca de fonte não alterou o motor. Pulado se o Node
não estiver instalado.

Exceção de propósito: os grupos em cascata com termo fixo (B-03, ADR 0005 do
tratamento), em que o Flask soma o termo fixo da última Classe e o app.js não.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from calculadora.filtros import resolver_filtros

RAIZ = Path(__file__).resolve().parents[2]
APP_JS = RAIZ / "5_Calculadora_Final" / "app.js"
FIXTURE = Path(__file__).parent / "fixtures" / "tarifas_2026-09-03.json"
SCRIPT = Path(__file__).parent / "paridade" / "executar_app_js.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not APP_JS.exists(),
    reason="Node.js ou 5_Calculadora_Final/app.js indisponível",
)


@pytest.fixture(scope="module")
def saidas_js(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("paridade")
    # O app.js espera a base como script (window.TARIFAS_GN = {...};).
    tarifas_js = pasta / "tarifas.js"
    payload = FIXTURE.read_text(encoding="utf-8")
    tarifas_js.write_text(f"window.TARIFAS_GN = {payload};", encoding="utf-8")
    destino = pasta / "saidas.json"
    subprocess.run(
        ["node", str(SCRIPT), str(tarifas_js), str(APP_JS), str(destino)],
        check=True,
        capture_output=True,
    )
    return json.loads(destino.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cliente_original():
    """App Flask lendo exatamente a mesma base usada pelo app.js."""
    from app import create_app

    return create_app(FIXTURE).test_client()


class _Extrator(HTMLParser):
    """Coleta textos de células (td/dt/dd/h3) e o conteúdo/atributos de elementos por id."""

    CELULAS = {"td", "dt", "dd", "h3"}

    def __init__(self):
        super().__init__()
        self.pilha = []  # (tag, id)
        self.celulas_por_id: dict[str, list[str]] = {}
        self.texto_por_id: dict[str, str] = {}
        self.oculto_por_id: dict[str, bool] = {}
        self.celulas_soltas: list[str] = []
        self._celula = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.oculto_por_id[attrs["id"]] = "hidden" in attrs
            self.celulas_por_id.setdefault(attrs["id"], [])
            self.texto_por_id.setdefault(attrs["id"], "")
        self.pilha.append((tag, attrs.get("id")))
        if tag in self.CELULAS:
            self._celula = []

    def handle_endtag(self, tag):
        if tag in self.CELULAS and self._celula is not None:
            texto = "".join(self._celula).strip()
            self.celulas_soltas.append(texto)
            for _, id_ in self.pilha:
                if id_:
                    self.celulas_por_id[id_].append(texto)
            self._celula = None
        while self.pilha:
            aberta, _ = self.pilha.pop()
            if aberta == tag:
                break

    def handle_data(self, data):
        if self._celula is not None:
            self._celula.append(data)
        for _, id_ in self.pilha:
            if id_:
                self.texto_por_id[id_] += data


def _extrair(html: str) -> _Extrator:
    extrator = _Extrator()
    extrator.feed(html)
    return extrator


def test_filtros_em_cascata_identicos(saidas_js, cliente_original):
    records = cliente_original.application.extensions["tarifas"].obter().records
    for caso in saidas_js["filtros"]:
        filtros = resolver_filtros(records, **caso["entrada"], segmento="").como_dict()
        assert filtros == caso["saida"], caso["entrada"]


def _grupos_b03(records) -> set[tuple]:
    return {(r["uf"], r["segmento_copa"], r["concessionaria"], r["segmento"])
            for r in records if r["cascata"] and r["termo_fixo"]}


def test_calculos_e_exibicao_identicos(saidas_js, cliente_original):
    grupos_b03 = _grupos_b03(cliente_original.application.extensions["tarifas"].obter().records)
    divergencias = []
    comparados = 0
    for caso in saidas_js["calculos"]:
        resposta = cliente_original.get("/api/calcular", query_string=caso["entrada"]).get_json()
        selecao = tuple(resposta["filtros"][k]["selecionado"] for k in ("uf", "segmento_copa", "concessionaria", "segmento"))
        if selecao in grupos_b03:
            continue
        comparados += 1
        py = _extrair(resposta["html"])
        calculado = resposta["resultado"]["ok"]

        ids_texto = ["volumeGlp", "volumeGn", "faturaLiquida", "faturaBruta", "resultadoResumo", "resultadoResumoCopia"]
        # Sem cálculo, o app.js mantinha na tela os cabeçalhos do cálculo anterior;
        # a versão Flask volta ao texto padrão, então só comparamos quando há cálculo.
        if calculado:
            ids_texto += ["faixasResumo", "pisCofinsHeader", "icmsHeader"]
        for id_ in ids_texto:
            if py.texto_por_id[id_].strip() != caso["texto"][id_]:
                divergencias.append((caso["entrada"], id_, py.texto_por_id[id_].strip(), caso["texto"][id_]))

        for id_, html_js in caso["html"].items():
            if py.celulas_por_id[id_] != _extrair(html_js).celulas_soltas:
                divergencias.append((caso["entrada"], id_, py.celulas_por_id[id_], _extrair(html_js).celulas_soltas))

        ocultos = {"comparisonCreditoPanel": py.oculto_por_id["comparisonCreditoPanel"]}
        if calculado:
            ocultos["termoFixoHeader"] = py.oculto_por_id["termoFixoHeader"]
        esperados = {k: v for k, v in caso["oculto"].items() if k in ocultos}
        if ocultos != esperados:
            divergencias.append((caso["entrada"], "oculto", ocultos, esperados))

    assert comparados > 1000
    assert not divergencias, f"{len(divergencias)} divergência(s). Primeiras: {divergencias[:5]}"
