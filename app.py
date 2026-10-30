"""Calculadora GLP x GN — servidor Flask lendo a Gold do Databricks.

Execução local:  set -a; . ./.env; set +a; python app.py
Configuração: variáveis GN_* e DATABRICKS_* (ver .env.example e README.md).
"""

from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from calculadora import formatacao
from calculadora.calculo import ResultadoCalculo, calcular, fatores_conversao
from calculadora.config import ConfigInvalida, carregar_config
from calculadora.dados import RepositorioTarifas, TarifasInvalidas, situacao_da_selecao
from calculadora.filtros import resolver_filtros
from calculadora.fonte import FonteDados, criar_fonte
from calculadora.fonte_json import FonteJson

BASE_DIR = Path(__file__).resolve().parent
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


def montar_contexto(base, args) -> dict:
    records = base.records
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

    resultado = calcular(records, **filtros.selecao(), tipo_entrada=tipo_entrada, volume=volume,
                         parametros=base.parametros)
    return {
        "filtros": filtros,
        "tipo_entrada": tipo_entrada,
        "volume_texto": volume_texto if volume_texto is not None else f"{VOLUME_PADRAO:g}",
        "resultado": resultado,
        "calculado": isinstance(resultado, ResultadoCalculo),
        "industrial": filtros.segmento_copa.selecionado.strip().upper() == "INDUSTRIAL",
        "situacao": situacao_da_selecao(records, **filtros.selecao()),
        "fator_glp_para_gn": fatores_conversao(base.parametros)[1],
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
        "termo_fixo": resultado.termo_fixo,
        "faixas": [vars(f) for f in resultado.faixas],
    }


def criar_repositorio(fonte: FonteDados | Path | str | None) -> RepositorioTarifas:
    """Sem fonte: lê a configuração do ambiente. Com caminho ou fonte: uso em testes, carga imediata."""
    if fonte is None:
        config = carregar_config()
        logging.getLogger("calculadora").info("Configuração: %s", config.resumo())
        repositorio = RepositorioTarifas(
            criar_fonte(config),
            cache_path=config.cache_path,
            recarga_minutos=config.recarga_minutos,
            max_idade_horas=config.base_max_idade_horas,
        )
        repositorio.iniciar(carga_sincrona=config.fonte == "json")
        return repositorio

    if isinstance(fonte, (str, Path)):
        fonte = FonteJson(Path(fonte))
    repositorio = RepositorioTarifas(fonte)
    repositorio.recarregar()
    return repositorio


def create_app(fonte: FonteDados | Path | str | None = None) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    repositorio = criar_repositorio(fonte)
    app.extensions["tarifas"] = repositorio

    app.add_template_filter(formatacao.moeda, "moeda")
    app.add_template_filter(formatacao.numero, "numero")
    app.add_template_filter(formatacao.faixa_maxima, "faixa_maxima")
    app.add_template_filter(formatacao.fator, "fator")
    app.add_template_filter(formatacao.data, "data")

    @app.errorhandler(TarifasInvalidas)
    def tarifas_invalidas(erro):
        app.logger.error("Base tarifária indisponível: %s", erro)
        return render_template("erro.html", mensagem=str(erro)), 503

    @app.get("/")
    def index():
        base = repositorio.obter()
        return render_template("index.html", base=base, base_antiga=repositorio.base_antiga(),
                               **montar_contexto(base, request.args))

    @app.get("/api/calcular")
    def api_calcular():
        base = repositorio.obter()
        contexto = montar_contexto(base, request.args)
        return jsonify(
            filtros=contexto["filtros"].como_dict(),
            resultado=resultado_como_dict(contexto["resultado"]),
            html=render_template("_resultados.html", **contexto),
        )

    @app.get("/api/tarifas")
    def api_tarifas():
        base = repositorio.obter()
        return jsonify(generated_at=base.generated_at, origem=base.origem, total=len(base.records),
                       parametros=base.parametros, records=list(base.records))

    # Liveness: só diz que o processo responde. Nunca consulta o Databricks, para uma queda
    # dele não reiniciar o pod; a situação da base vai no corpo.
    @app.get("/saude")
    def saude():
        return jsonify(repositorio.estado())

    # Readiness: pronto só com base válida em memória (Gold ou cópia local).
    @app.get("/saude/pronto")
    def saude_pronto():
        estado = repositorio.estado()
        return jsonify(estado), (503 if estado["status"] == "sem_base" else 200)

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
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        app = create_app()
    except ConfigInvalida as erro:
        print(erro, file=sys.stderr)
        sys.exit(2)
    host = os.environ.get("HOST", "127.0.0.1")  # use 0.0.0.0 para abrir na rede interna
    porta = int(os.environ.get("PORTA", "5000"))
    print(f"Calculadora GLP x GN em http://127.0.0.1:{porta}  (Ctrl+C para encerrar)")
    if os.environ.get("FLASK_DEBUG") == "1":
        app.run(host=host, port=porta, debug=True)
    else:
        from waitress import serve

        serve(app, host=host, port=porta)
