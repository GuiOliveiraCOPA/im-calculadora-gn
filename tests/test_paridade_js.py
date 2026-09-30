"""Garante que a versão Flask exibe exatamente o que o app.js original exibia.

Roda o 5_Calculadora_Final/app.js em Node (DOM simulado) para centenas de
cenários — todas as combinações da base × volumes × GLP/GN — e compara texto
a texto com o HTML gerado pelo Python. Pulado se o Node não estiver instalado.
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
VERSAO_ORIGINAL = RAIZ / "5_Calculadora_Final"
SCRIPT = Path(__file__).parent / "paridade" / "executar_app_js.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (VERSAO_ORIGINAL / "app.js").exists(),
    reason="Node.js ou 5_Calculadora_Final/app.js indisponível",
)


@pytest.fixture(scope="module")
def saidas_js(tmp_path_factory):
    destino = tmp_path_factory.mktemp("paridade") / "saidas.json"
    subprocess.run(
        ["node", str(SCRIPT), str(VERSAO_ORIGINAL / "tarifas.js"), str(VERSAO_ORIGINAL / "app.js"), str(destino)],
        check=True,
        capture_output=True,
    )
    return json.loads(destino.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cliente_original():
    """App Flask lendo exatamente a mesma base usada pelo app.js."""
    from app import create_app

    texto = (VERSAO_ORIGINAL / "tarifas.js").read_text(encoding="utf-8-sig").strip()
    payload = texto.removeprefix("window.TARIFAS_GN = ").removesuffix(";")
    caminho = Path(__file__).parent / "paridade" / "_tarifas_original.json"
    caminho.write_text(payload, encoding="utf-8")
    try:
        yield create_app(caminho).test_client()
    finally:
        caminho.unlink(missing_ok=True)


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


def test_calculos_e_exibicao_identicos(saidas_js, cliente_original):
    divergencias = []
    for caso in saidas_js["calculos"]:
        resposta = cliente_original.get("/api/calcular", query_string=caso["entrada"]).get_json()
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

    assert len(saidas_js["calculos"]) > 1000
    assert not divergencias, f"{len(divergencias)} divergência(s). Primeiras: {divergencias[:5]}"
