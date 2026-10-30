"""Configuração por variáveis de ambiente (GN_*, DATABRICKS_*).

Nada de host, caminho ou segredo fixo: a troca de ambiente (local, Docker,
Kubernetes) é só mudar variáveis. Os erros são reunidos e reportados de uma vez.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# ambiente -> (catálogo, schema) da Gold
AMBIENTES = {
    "dev": ("marketing_dev", "dbt_guilherme_oliveira"),
    "hml": ("marketing_hml", "marketing_gold"),
    "prd": ("marketing_prd", "marketing_gold"),
}
FONTES = ("databricks", "json")
TIPOS_AUTH = ("pat", "oauth_m2m", "oauth_u2m")

TABELA_PADRAO = "fct_gn_tarifa_vigente_calculadora"
TABELA_PARAMETROS_PADRAO = "fct_gn_parametro_vigente_calculadora"
CACHE_PADRAO = "./.cache/tarifas.json"

# Catálogo, schema e tabela entram no SQL: só identificadores simples.
_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigInvalida(Exception):
    """Variáveis de ambiente ausentes ou com valor inválido."""

    def __init__(self, problemas: list[str]):
        self.problemas = problemas
        super().__init__("Configuração inválida:\n- " + "\n- ".join(problemas))


@dataclass(frozen=True)
class Config:
    ambiente: str
    fonte: str
    catalogo: str
    schema: str
    tabela: str
    tabela_parametros: str
    recarga_minutos: int
    timeout_consulta_s: int
    cache_path: Path
    base_max_idade_horas: int
    arquivo_json: Path | None = None
    auth_tipo: str = ""
    # Host, http_path e segredos fora do repr: a config pode ser impressa sem vazá-los.
    databricks_host: str = field(default="", repr=False)
    databricks_http_path: str = field(default="", repr=False)
    token: str = field(default="", repr=False)
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)

    @property
    def tabela_completa(self) -> str:
        return f"{self.catalogo}.{self.schema}.{self.tabela}"

    @property
    def tabela_parametros_completa(self) -> str:
        return f"{self.catalogo}.{self.schema}.{self.tabela_parametros}"

    def resumo(self) -> dict:
        """Dados seguros para log: sem host, token nem secret."""
        return {
            "ambiente": self.ambiente,
            "fonte": self.fonte,
            "tabela": self.tabela_completa,
            "auth_tipo": self.auth_tipo or None,
            "recarga_minutos": self.recarga_minutos,
            "base_max_idade_horas": self.base_max_idade_horas,
        }


def _inteiro_positivo(env: Mapping[str, str], nome: str, padrao: int, problemas: list[str]) -> int:
    bruto = env.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        valor = int(bruto)
    except ValueError:
        problemas.append(f"{nome} deve ser um número inteiro (recebido {bruto!r})")
        return padrao
    if valor < 1:
        problemas.append(f"{nome} deve ser maior que zero (recebido {valor})")
        return padrao
    return valor


def _escolha(env: Mapping[str, str], nome: str, padrao: str, validos: tuple[str, ...], problemas: list[str]) -> str:
    valor = env.get(nome, "").strip().lower() or padrao
    if valor not in validos:
        problemas.append(f"{nome} deve ser um de {', '.join(validos)} (recebido {valor!r})")
    return valor


def _exigir(env: Mapping[str, str], nome: str, problemas: list[str], motivo: str = "") -> str:
    valor = env.get(nome, "").strip()
    if not valor:
        problemas.append(f"{nome} é obrigatória{motivo}")
    return valor


def _identificador(nome: str, valor: str, problemas: list[str]) -> None:
    if not _IDENTIFICADOR.match(valor):
        problemas.append(f"{nome} deve conter só letras, números e '_' (recebido {valor!r})")


def carregar_config(env: Mapping[str, str] | None = None) -> Config:
    """Lê e valida a configuração; levanta ConfigInvalida com todos os problemas."""
    env = os.environ if env is None else env
    problemas: list[str] = []

    ambiente = _escolha(env, "GN_AMBIENTE", "dev", tuple(AMBIENTES), problemas)
    fonte = _escolha(env, "GN_FONTE", "databricks", FONTES, problemas)
    catalogo_amb, schema_amb = AMBIENTES.get(ambiente, ("", ""))
    catalogo = env.get("GN_CATALOGO", "").strip() or catalogo_amb
    schema = env.get("GN_SCHEMA", "").strip() or schema_amb
    tabela = env.get("GN_TABELA_TARIFAS", "").strip() or TABELA_PADRAO
    if ambiente in AMBIENTES:
        _identificador("GN_CATALOGO", catalogo, problemas)
        _identificador("GN_SCHEMA", schema, problemas)
    _identificador("GN_TABELA_TARIFAS", tabela, problemas)
    tabela_parametros = env.get("GN_TABELA_PARAMETROS", "").strip() or TABELA_PARAMETROS_PADRAO
    _identificador("GN_TABELA_PARAMETROS", tabela_parametros, problemas)

    recarga = _inteiro_positivo(env, "GN_RECARGA_MINUTOS", 30, problemas)
    timeout = _inteiro_positivo(env, "GN_TIMEOUT_CONSULTA_S", 60, problemas)
    max_idade = _inteiro_positivo(env, "GN_BASE_MAX_IDADE_HORAS", 72, problemas)
    cache_path = Path(env.get("GN_CACHE_PATH", "").strip() or CACHE_PADRAO)

    arquivo_json = None
    host = http_path = auth_tipo = token = client_id = client_secret = ""
    if fonte == "json":
        arquivo_json = Path(_exigir(env, "GN_ARQUIVO_JSON", problemas, " quando GN_FONTE=json") or ".")
    elif fonte == "databricks":
        host = _exigir(env, "DATABRICKS_HOST", problemas)
        # Aceita o host com ou sem https:// e barra final.
        host = re.sub(r"^https?://", "", host).rstrip("/")
        http_path = _exigir(env, "DATABRICKS_HTTP_PATH", problemas)
        # PAT só em dev; HML/PRD usam service principal.
        auth_tipo = _escolha(env, "GN_AUTH_TIPO", "pat" if ambiente == "dev" else "oauth_m2m", TIPOS_AUTH, problemas)
        if auth_tipo == "pat":
            token = _exigir(env, "DATABRICKS_TOKEN", problemas, " quando GN_AUTH_TIPO=pat")
        elif auth_tipo == "oauth_m2m":
            client_id = _exigir(env, "DATABRICKS_CLIENT_ID", problemas, " quando GN_AUTH_TIPO=oauth_m2m")
            client_secret = _exigir(env, "DATABRICKS_CLIENT_SECRET", problemas, " quando GN_AUTH_TIPO=oauth_m2m")

    if problemas:
        raise ConfigInvalida(problemas)

    return Config(
        ambiente=ambiente,
        fonte=fonte,
        catalogo=catalogo,
        schema=schema,
        tabela=tabela,
        tabela_parametros=tabela_parametros,
        recarga_minutos=recarga,
        timeout_consulta_s=timeout,
        cache_path=cache_path,
        base_max_idade_horas=max_idade,
        arquivo_json=arquivo_json,
        databricks_host=host,
        databricks_http_path=http_path,
        auth_tipo=auth_tipo,
        token=token,
        client_id=client_id,
        client_secret=client_secret,
    )
