"""Diagnóstico da conexão com a Gold, camada por camada.

Usa as mesmas variáveis da calculadora (GN_*, DATABRICKS_*) e para na primeira camada
que falhar, dizendo qual é. Serve na máquina local, no contêiner e num pod de teste:

    python scripts/testar_conexao.py
    python scripts/testar_conexao.py --tabela-proibida marketing_prd.marketing_gold.outra_tabela

Com --tabela-proibida, confere também que o acesso é mínimo: a leitura dessa tabela TEM de falhar.
Código de saída: 0 ok; 1 config; 2 DNS; 3 TCP 443; 4 autenticação/warehouse; 5 tabelas do contrato;
6 base inválida; 7 permissão maior que a necessária.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calculadora.config import ConfigInvalida, carregar_config  # noqa: E402
from calculadora.dados import TarifasInvalidas, montar_base  # noqa: E402
from calculadora.fonte_databricks import FonteDatabricks  # noqa: E402


def etapa(numero: int, titulo: str):
    print(f"[{numero}] {titulo}...", flush=True)
    return time.monotonic()


def ok(inicio: float, detalhe: str = "") -> None:
    print(f"    ok ({time.monotonic() - inicio:.1f}s){' - ' + detalhe if detalhe else ''}", flush=True)


def falha(codigo: int, mensagem: str, dica: str) -> int:
    print(f"    FALHA: {mensagem}\n    O que verificar: {dica}", flush=True)
    return codigo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tabela-proibida", help="tabela que o usuário/service principal NÃO pode ler")
    args = parser.parse_args()

    inicio = etapa(1, "Configuração")
    try:
        config = carregar_config()
    except ConfigInvalida as exc:
        return falha(1, str(exc), "variáveis do .env / ConfigMap / Secret (ver .env.example).")
    if config.fonte != "databricks":
        return falha(1, f"GN_FONTE={config.fonte}", "o diagnóstico só faz sentido com GN_FONTE=databricks.")
    ok(inicio, f"{config.resumo()}")

    host = config.databricks_host
    inicio = etapa(2, f"DNS de {host}")
    try:
        enderecos = sorted({info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    except OSError as exc:
        return falha(2, str(exc), "DNS do cluster/rede; com Private Link, a zona privatelink.azuredatabricks.net.")
    ok(inicio, ", ".join(enderecos))

    inicio = etapa(3, "Conexão TCP na porta 443")
    try:
        socket.create_connection((host, 443), timeout=10).close()
    except OSError as exc:
        return falha(3, str(exc), "egress do cluster/firewall até o workspace; proxy (HTTPS_PROXY/NO_PROXY).")
    ok(inicio)

    fonte = FonteDatabricks(config)
    inicio = etapa(4, f"Autenticação ({config.auth_tipo}) e SQL Warehouse (SELECT 1)")
    try:
        with fonte._conectar() as conexao, conexao.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchall()
    except Exception as exc:  # noqa: BLE001 - o diagnóstico mostra qualquer erro do conector
        return falha(4, f"{type(exc).__name__}: {exc}",
                     "token/service principal (expirado? rotacionado?), DATABRICKS_HTTP_PATH, permissão CAN USE "
                     "no warehouse, IP access list do workspace. Warehouse desligado pode levar minutos para ligar.")
    ok(inicio)

    inicio = etapa(5, f"Leitura de {config.tabela_completa} e {config.tabela_parametros_completa}")
    try:
        payload = fonte.carregar()
    except Exception as exc:  # noqa: BLE001
        return falha(5, f"{type(exc).__name__}: {exc}",
                     "USE CATALOG/USE SCHEMA e SELECT nas duas tabelas do contrato; nome do schema por ambiente.")
    records = payload["records"]
    ok(inicio, f"{len(records)} registros, gerada em {payload['generated_at'] or '?'}, parâmetros {payload['parametros']}")

    inicio = etapa(6, "Validação do contrato (a mesma da calculadora)")
    try:
        montar_base(payload, "databricks", "")
    except TarifasInvalidas as exc:
        return falha(6, str(exc), "o modelo dbt fct_gn_tarifa_vigente_calculadora (contrato de 23 colunas).")
    status = Counter(r.get("status_atualizacao") for r in records)
    origens = Counter(r.get("origem_valor") for r in records)
    ok(inicio, f"{len({r['uf'] for r in records})} UFs; status {dict(status)}; origem {dict(origens)}")

    if args.tabela_proibida:
        inicio = etapa(7, f"Acesso mínimo: leitura de {args.tabela_proibida} deve ser negada")
        try:
            with fonte._conectar() as conexao, conexao.cursor() as cursor:
                cursor.execute(f"SELECT 1 FROM {args.tabela_proibida} LIMIT 1")
                cursor.fetchall()
        except Exception as exc:  # noqa: BLE001
            ok(inicio, f"negada como esperado ({type(exc).__name__})")
        else:
            return falha(7, "a leitura foi permitida", "restringir o SELECT do service principal às 2 tabelas.")

    print("Conexão com a Gold ok.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
