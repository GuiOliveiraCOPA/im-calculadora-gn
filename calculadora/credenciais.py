"""Autenticação no Databricks, escolhida por GN_AUTH_TIPO.

- pat: token pessoal (só dev).
- oauth_m2m: service principal (client id + secret), para HML/PRD e Kubernetes.
- oauth_u2m: login local pela CLI do Databricks (`databricks auth login`); usa o
  perfil de DATABRICKS_CONFIG_PROFILE no ~/.databrickscfg, se informado.

Os dois OAuth passam pelo databricks-sdk. O objeto do SDK só é criado quando o
conector abre a conexão: nada de rede ao montar a configuração.
"""

from __future__ import annotations

import os

from calculadora.config import Config


def parametros_autenticacao(config: Config) -> dict:
    """Argumentos de autenticação para databricks.sql.connect."""
    if config.auth_tipo == "pat":
        return {"access_token": config.token}

    host = f"https://{config.databricks_host}"
    if config.auth_tipo == "oauth_m2m":
        def configurar():
            return _config_sdk(host=host, client_id=config.client_id, client_secret=config.client_secret,
                               auth_type="oauth-m2m")
    elif config.auth_tipo == "oauth_u2m":
        def configurar():
            return _config_sdk(host=host, profile=os.environ.get("DATABRICKS_CONFIG_PROFILE") or None,
                               auth_type="databricks-cli")
    else:
        raise ValueError(f"GN_AUTH_TIPO desconhecido: {config.auth_tipo!r}")

    # O conector chama credentials_provider() ao conectar e usa o resultado para montar os cabeçalhos.
    return {"credentials_provider": lambda: configurar().authenticate}


def _config_sdk(**kwargs):
    from databricks.sdk.core import Config as ConfigSdk

    return ConfigSdk(**kwargs)
