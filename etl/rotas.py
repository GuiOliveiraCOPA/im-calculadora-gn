"""Tela interna do ETL (/interno/etl). Não há link para ela no site.

Se a variável ETL_SENHA estiver definida, a tela pede usuário/senha (autenticação básica;
qualquer usuário, a senha é a de ETL_SENHA).
"""

from __future__ import annotations

import hmac
from datetime import datetime
from urllib.parse import urlsplit

from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_file, url_for)

from calculadora.dados import TarifasInvalidas
from etl.agendamento import (DIAS_SEMANA, AgendamentoInvalido, carregar_agendamento, descrever, proxima_execucao,
                             salvar_agendamento)
from etl.executor import FORMATO_DATA, EtlEmExecucao

bp = Blueprint("etl", __name__, url_prefix="/interno/etl")
LIMITE_LEITURA_LOG = 512 * 1024


def _executor():
    return current_app.extensions["etl_executor"]


def _agendador():
    return current_app.extensions.get("etl_agendador")


@bp.before_request
def proteger():
    senha = _executor().config.senha
    if senha:
        auth = request.authorization
        if not auth or not hmac.compare_digest((auth.password or "").encode(), senha.encode()):
            return Response("Acesso restrito.", 401, {"WWW-Authenticate": 'Basic realm="ETL Calculadora GN"'})
    if request.method == "POST":
        origem = request.headers.get("Origin")
        if origem and urlsplit(origem).netloc != request.host:
            abort(403)


@bp.after_request
def sem_indexacao(resposta):
    resposta.headers["X-Robots-Tag"] = "noindex, nofollow"
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


def _situacao_base() -> dict:
    """Base que a calculadora está usando agora."""
    repositorio = current_app.extensions["tarifas"]
    try:
        base = repositorio.obter()
        return {"ok": True, "registros": len(base.records), "generated_at": base.generated_at,
                "ufs": len({r["uf"] for r in base.records}), "mensagem": ""}
    except TarifasInvalidas as exc:
        return {"ok": False, "registros": 0, "generated_at": "", "ufs": 0, "mensagem": str(exc)}


def _situacao_agendamento() -> dict:
    executor = _executor()
    agendamento = carregar_agendamento(executor.config.agendamento_json)
    agendador = _agendador()
    proxima = agendador.proxima() if agendador else proxima_execucao(agendamento, datetime.now())
    return {
        **agendamento,
        "descricao": descrever(agendamento),
        "agendador_ativo": bool(agendador and agendador.is_alive()),
        "proxima": proxima.strftime(FORMATO_DATA) if proxima else "",
    }


def _status() -> dict:
    executor = _executor()
    return {
        "agora": datetime.now().strftime(FORMATO_DATA),
        "em_execucao": executor.em_execucao(),
        "base": _situacao_base(),
        "agendamento": _situacao_agendamento(),
        "historico": executor.historico()[:30],
    }


@bp.get("/")
def painel():
    executor = _executor()
    cfg = executor.config
    return render_template(
        "etl.html",
        status=_status(),
        logs=executor.logs_disponiveis()[:50],
        dias_semana=DIAS_SEMANA,
        sem_senha=not cfg.senha,
        planilha_final=cfg.planilha_final.is_file(),
        processo_dir=cfg.processo_dir,
    )


@bp.get("/status")
def status():
    return jsonify(_status())


@bp.post("/executar")
def executar():
    form = request.form
    try:
        execucao = _executor().iniciar(
            origem="manual",
            responsavel=form.get("responsavel", ""),
            ufs=form.get("ufs", ""),
            skip_run=form.get("skip_run") == "1",
            mesmo_com_erro=form.get("mesmo_com_erro") == "1",
        )
        flash(f"Atualização iniciada. Log: {execucao['log']}", "ok")
    except EtlEmExecucao as exc:
        flash(str(exc), "erro")
    return redirect(url_for("etl.painel"))


@bp.post("/agendamento")
def agendamento():
    form = request.form
    try:
        salvo = salvar_agendamento(_executor().config.agendamento_json, {
            "ativo": form.get("ativo") == "1",
            "horario": form.get("horario", ""),
            "dias": form.getlist("dias"),
            "mesmo_com_erro": form.get("mesmo_com_erro") == "1",
        })
        flash(f"Agendamento salvo: {descrever(salvo)}.", "ok")
    except AgendamentoInvalido as exc:
        flash(str(exc), "erro")
    return redirect(url_for("etl.painel"))


@bp.get("/log/<nome>")
def ler_log(nome: str):
    """Conteúdo do log a partir do byte `desde` (para acompanhar a execução ao vivo)."""
    caminho = _executor().caminho_log(nome)
    if caminho is None:
        abort(404)
    desde = max(request.args.get("desde", 0, type=int), 0)
    with open(caminho, "rb") as arquivo:
        tamanho = arquivo.seek(0, 2)
        if desde > tamanho:
            desde = 0
        if not desde and tamanho > LIMITE_LEITURA_LOG:
            desde = tamanho - LIMITE_LEITURA_LOG
        arquivo.seek(desde)
        bruto = arquivo.read(LIMITE_LEITURA_LOG)
    # Logs antigos do .bat podem estar em cp1252; os novos são utf-8.
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252", errors="replace")
    return jsonify(nome=nome, desde=desde, tamanho=desde + len(bruto), texto=texto)


@bp.get("/log/<nome>/download")
def baixar_log(nome: str):
    caminho = _executor().caminho_log(nome)
    if caminho is None:
        abort(404)
    return send_file(caminho, mimetype="text/plain", as_attachment=True, download_name=nome)


@bp.get("/planilha-final")
def planilha_final():
    caminho = _executor().config.planilha_final
    if not caminho.is_file():
        abort(404)
    return send_file(caminho, as_attachment=True, download_name=caminho.name)
