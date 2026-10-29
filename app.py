"""Calculadora GLP x GN — servidor Flask.

Execução local:  python app.py   (ou Iniciar_Calculadora.bat)
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from calculadora import formatacao
from calculadora.calculo import ResultadoCalculo, calcular
from calculadora.dados import RepositorioTarifas, TarifasInvalidas
from calculadora.filtros import resolver_filtros

BASE_DIR = Path(__file__).resolve().parent
TARIFAS_PADRAO = BASE_DIR / "data" / "tarifas.json"
MAPA_DIR = Path(os.environ.get("MAPA_GN_DIR", BASE_DIR / "mapa"))

VOLUME_PADRAO = 5000.0
TIPOS_ENTRADA = ("glp", "gn")


def ler_volume(texto: str | None) -> float:
    """Volume informado; vazio, inválido, negativo ou não finito vira 0 (sem cálculo)."""
    if texto is None:
        return VOLUME_PADRAO
    try:
        volume = float(texto.strip().replace(",", ".")) if texto.strip() else 0.0
    except ValueError:
        return 0.0
    return volume if math.isfinite(volume) else 0.0


def montar_contexto(records, args) -> dict:
    filtros = resolver_filtros(
        records,
        uf=args.get("uf"),
        segmento_copa=args.get("segmento_copa"),
        concessionaria=args.get("concessionaria"),
        segmento=args.get("segmento"),
    )
    tipo_entrada = args.get("tipo_entrada", "glp")
    if tipo_entrada not in TIPOS_ENTRADA:
        tipo_entrada = "glp"
    volume_texto = args.get("volume")
    volume = ler_volume(volume_texto)

    resultado = calcular(records, **filtros.selecao(), tipo_entrada=tipo_entrada, volume=volume)
    return {
        "filtros": filtros,
        "tipo_entrada": tipo_entrada,
        "volume_texto": volume_texto if volume_texto is not None else f"{VOLUME_PADRAO:g}",
        "resultado": resultado,
        "calculado": isinstance(resultado, ResultadoCalculo),
        "industrial": filtros.segmento_copa.selecionado.strip().upper() == "INDUSTRIAL",
    }


def resultado_como_dict(resultado) -> dict:
    if not isinstance(resultado, ResultadoCalculo):
        return {"ok": False, "mensagem": resultado.mensagem}
    return {
        "ok": True,
        "cascata": resultado.cascata,
        "entrada": "glp" if resultado.entrada_glp else "gn",
        "volume_glp_kg": resultado.volume_glp,
        "volume_gn_m3": resultado.volume_gn,
        "aliquota_pis_cofins": resultado.aliquota_pis_cofins,
        "aliquota_icms": resultado.aliquota_icms,
        "fatura_liquida": resultado.fatura_liquida,
        "total_pis_cofins": resultado.total_pis_cofins,
        "total_icms": resultado.total_icms,
        "fatura_bruta_gn": resultado.fatura_bruta_gn,
        "fatura_bruta_glp": resultado.fatura_bruta_glp,
        "tarifa_liquida_unitaria_glp": resultado.tarifa_liquida_unitaria_glp,
        "tarifa_bruta_unitaria_glp": resultado.tarifa_bruta_unitaria_glp,
        "tarifa_liquida_unitaria_gn": resultado.tarifa_liquida_unitaria_gn,
        "tarifa_bruta_unitaria_gn": resultado.tarifa_bruta_unitaria_gn,
        "gn_bruto_por_kg_glp": resultado.gn_bruto_por_kg_glp,
        "faixas": [vars(f) for f in resultado.faixas],
    }


def create_app(caminho_tarifas: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    repositorio = RepositorioTarifas(caminho_tarifas or Path(os.environ.get("TARIFAS_GN_JSON", TARIFAS_PADRAO)))
    app.extensions["tarifas"] = repositorio

    app.add_template_filter(formatacao.moeda, "moeda")
    app.add_template_filter(formatacao.numero, "numero")
    app.add_template_filter(formatacao.faixa_maxima, "faixa_maxima")

    @app.errorhandler(TarifasInvalidas)
    def tarifas_invalidas(erro):
        app.logger.error("Base tarifária inválida: %s", erro)
        return render_template("erro.html", mensagem=str(erro)), 503

    @app.get("/")
    def index():
        base = repositorio.obter()
        return render_template("index.html", base=base, **montar_contexto(base.records, request.args))

    @app.get("/api/calcular")
    def api_calcular():
        base = repositorio.obter()
        contexto = montar_contexto(base.records, request.args)
        return jsonify(
            filtros=contexto["filtros"].como_dict(),
            resultado=resultado_como_dict(contexto["resultado"]),
            html=render_template("_resultados.html", **contexto),
        )

    @app.get("/api/tarifas")
    def api_tarifas():
        base = repositorio.obter()
        return jsonify(generated_at=base.generated_at, total=len(base.records), records=list(base.records))

    @app.get("/saude")
    def saude():
        base = repositorio.obter()
        return jsonify(status="ok", registros=len(base.records), generated_at=base.generated_at)

    @app.get("/mapa/")
    @app.get("/mapa/<path:arquivo>")
    def mapa(arquivo: str = "index.html"):
        if not MAPA_DIR.is_dir():
            abort(404)
        return send_from_directory(MAPA_DIR, arquivo)

    # O mapa tem um link "Voltar para a calculadora" apontando para a versão estática.
    @app.get("/5_Calculadora_Final/index.html")
    def voltar_do_mapa():
        return redirect(url_for("index"))

    return app


if __name__ == "__main__":
    app = create_app()
    app.extensions["tarifas"].obter()  # falha logo na partida se a base estiver inválida
    host = os.environ.get("HOST", "127.0.0.1")  # use 0.0.0.0 para abrir na rede interna
    porta = int(os.environ.get("PORTA", "5000"))
    print(f"Calculadora GLP x GN em http://127.0.0.1:{porta}  (Ctrl+C para encerrar)")
    if os.environ.get("FLASK_DEBUG") == "1":
        app.run(host=host, port=porta, debug=True)
    else:
        from waitress import serve

        serve(app, host=host, port=porta)
