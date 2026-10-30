# Calculadora GLP x GN (Flask) — lendo a Gold do Databricks

Site da calculadora GLP x GN e do mapa de GN. As tarifas vêm da Gold
(`<catálogo>.<schema>.fct_gn_tarifa_vigente_calculadora` e `fct_gn_parametro_vigente_calculadora`),
preparada no Databricks pelo Job de ingestão (`8_pipeline_calculadora_gn`) e pelo dbt
(`DBT_MARKETING`), que rodam toda manhã. Este repositório não coleta nem trata dados.

```
Databricks (Unity Catalog)                 Flask (este repositório)
SQL Warehouse  ◄── HTTPS 443 ──  fonte_databricks.py ─ credenciais.py (pat | oauth_m2m | oauth_u2m)
                                  dados.py: base em memória, recarga em segundo plano, validação
                                  cache_local.py: cópia da última base válida
                                  calculo / filtros / formatacao  →  app.py: telas, /api/*, /saude, /mapa/
```

**A tela nunca espera o Databricks.** A base é lida na partida e a cada `GN_RECARGA_MINUTOS`
(padrão 30) em uma thread; as requisições usam a última base válida em memória.

| Situação | Comportamento |
|---|---|
| Databricks ok | Carrega, valida e grava a cópia local (`/saude`: `origem = databricks`) |
| Databricks fora, com cópia local | Usa a cópia (`status = degradado`) e tenta de novo a cada 5 min |
| Databricks fora, sem cópia | Tela 503 e `/saude/pronto` 503 até a primeira carga |
| Recarga traz base inválida | Descarta e mantém a última válida (base inválida nunca calcula) |
| Base com mais de `GN_BASE_MAX_IDADE_HORAS` (72) | Continua calculando, com aviso na tela e `status = degradado` |

## Rodar em desenvolvimento

```bash
python -m venv .venv && . .venv/Scripts/activate      # Linux/macOS: . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # preencha host, http_path e a credencial
set -a; . ./.env; set +a                               # o app lê só variáveis de ambiente
python scripts/testar_conexao.py                       # diagnóstico camada por camada
python app.py                                          # http://127.0.0.1:5000
```

Sem Databricks (offline), use a fixture: `GN_FONTE=json` e
`GN_ARQUIVO_JSON=tests/fixtures/tarifas_2026-09-03.json`.

Login local sem token (`GN_AUTH_TIPO=oauth_u2m`): `databricks auth login --host https://<host>` e,
se houver mais de um perfil no `~/.databrickscfg`, `DATABRICKS_CONFIG_PROFILE=<perfil>`.

> **Git Bash no Windows:** ele converte variáveis que parecem caminho POSIX ao chamar o Python, e o
> `DATABRICKS_HTTP_PATH` (`/sql/1.0/...`) vira `C:/Program Files/Git/sql/...`. O sintoma é
> `RequestError` na etapa 4 do `testar_conexao.py`. Rode antes `export MSYS2_ENV_CONV_EXCL=DATABRICKS_HTTP_PATH`,
> ou use PowerShell ou o Docker.

### Docker

```bash
docker compose up -d --build
docker compose exec calculadora python scripts/testar_conexao.py
docker build --target teste .          # roda o pytest dentro da imagem
```

A imagem não leva dados nem credenciais. Roda como usuário sem privilégio (uid 10001) e só
grava a cópia local em `/tmp/gn_cache`.

## Configuração

Todas as variáveis estão no [.env.example](.env.example). As principais:

| Variável | Padrão | Uso |
|---|---|---|
| `GN_AMBIENTE` | `dev` | dev → `marketing_dev.dbt_guilherme_oliveira`, hml → `marketing_hml.marketing_gold`, prd → `marketing_prd.marketing_gold` |
| `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH` | — | Workspace e SQL Warehouse |
| `GN_AUTH_TIPO` | `pat` em dev, `oauth_m2m` em hml/prd | `pat` (`DATABRICKS_TOKEN`), `oauth_m2m` (`DATABRICKS_CLIENT_ID`/`_SECRET`), `oauth_u2m` (CLI) |
| `GN_RECARGA_MINUTOS` | `30` | Intervalo de recarga |
| `GN_CACHE_PATH` | `./.cache/tarifas.json` | Cópia local da última base válida |
| `GN_FONTE` | `databricks` | `json` para rodar com arquivo (`GN_ARQUIVO_JSON`) |

## Rotas

| Rota | Descrição |
|---|---|
| `/` | Calculadora |
| `/api/calcular` | Cálculo e filtros (usado pela tela) |
| `/api/tarifas` | Base em memória, com origem e parâmetros |
| `/saude` | Liveness: sempre 200; no corpo, `status` (`ok`, `degradado`, `sem_base`), origem, data e último erro. Não consulta o Databricks |
| `/saude/pronto` | Readiness: 200 com base válida em memória, 503 sem base |
| `/mapa/` | Mapa de GN (pasta `mapa/`) |

## Dados e regras de cálculo

- **Contrato:** 23 colunas da `fct_gn_tarifa_vigente_calculadora`. `tarifa` e `termo_fixo` já vêm
  líquidos (`preco_concessionaria = 'sem impostos'`), e o site só aplica o gross-up.
- **Parâmetros:** `FATOR_GN_PARA_GLP`, `FATOR_GLP_PARA_GN` (obrigatórios) e `ALIQUOTA_MONOFASICA_GLP`
  vêm da `fct_gn_parametro_vigente_calculadora`. Sem os fatores, a base é inválida. Sem a monofásica,
  vale a constante do `calculo.py`.
- **Situação da tarifa:** a tela mostra `atualizado_em`, `vigencia_inicio` e `deliberacao` (quando vier) da combinação escolhida,
  e um aviso quando `status_atualizacao = desatualizada`, quando o valor é da base manual ou quando
  é o último valor válido mantido (`origem_valor`).
- **Termo fixo na cascata (B-03, ADR 0005 do tratamento):** soma o termo fixo líquido da última
  Classe atingida. É a única regra diferente do `app.js` original.
- **Consumo mínimo (P-02):** segue o contorno da Gold (rateio na cascata; termo fixo sem cascata).

## Testes

```bash
pytest                    # unitários, repositório, contrato com conexão falsa
pytest -m databricks      # integração real (com as variáveis do .env carregadas)
```

`tests/test_paridade_js.py` compara milhares de cenários com o `5_Calculadora_Final/app.js` sobre a
fixture congelada. Precisa de Node.js e roda pulando os grupos do B-03.

## Kubernetes

Os modelos estão em [deploy/k8s/](deploy/k8s/), e o guia, com o checklist de rede e segurança, em
[docs/KUBERNETES.md](docs/KUBERNETES.md).
