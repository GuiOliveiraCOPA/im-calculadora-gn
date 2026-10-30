# Plano de execução — Calculadora GN Flask lendo a Gold (`10_Calculadora_Flask`)

Status: **em execução**. Fase 0 e 1.1 concluídas e commitadas. Em 2026-10-30: 1.2 a 1.6, 2.1 e 2.4 feitas; 1.8 e 2.5 em parte (`README.md`, `docs/KUBERNETES.md`). Pendentes: 1.7 (conferência Gold × base atual), 2.2/2.3 (service principal e rede, com a infra) e Fase 3.

Notas de 2026-10-30:
- O ETL antigo do IM (`etl/`, `processo_im/`, tela `/interno/etl`), trazido da `main` no commit `78724cb`, saiu da `10`. Ela fica só com calculadora + mapa; o mapa voltou para `mapa/` (D-02).
- Leitura real da Gold de **prd** validada com `scripts/testar_conexao.py` e `pytest -m databricks` (perfil local `oauth_u2m`): 454 registros, 17 UFs, contrato válido.
- **D-03 resolvida:** a `fct_gn_parametro_vigente_calculadora` de prd já traz `ALIQUOTA_MONOFASICA_GLP` (1,6377). O site usa os 3 parâmetros da Gold; sem a monofásica, vale a constante.
- **B-03 (ADR 0005) entrou no cálculo:** soma o termo fixo da última Classe atingida na cascata. A paridade com o `app.js` exclui só esses grupos. Na fixture, os outros 1.950 cenários deram idênticos à versão anterior.
- `oauth_u2m` usa o login da CLI do Databricks (`DATABRICKS_CONFIG_PROFILE` opcional), pelo databricks-sdk.

Notas da 0.2: a estrutura foi copiada da `6` sem os itens da 4.4 (sem `data/`) e com `mapa/` (cópia idêntica da `4_Mapa_GN`). `app.py`, `Dockerfile` e `docker-compose.yml` ainda são idênticos aos da `6`: o caminho do mapa (`4_Mapa_GN`), o `COPY data/` e o `TARIFAS_PADRAO` serão tratados nas tarefas 1.5 e 2.1.

Notas da 0.3: a fixture `tests/fixtures/tarifas_2026-09-03.json` (459 registros, `generated_at` 2026-09-03 10:33:36) é cópia da `6/data/tarifas.json`, idêntica ao `5_Calculadora_Final/tarifas.js`. Só `source` e `schema_reference` foram trocados por texto neutro (tinham caminho local do OneDrive com usuário do Windows). A paridade gera um `tarifas.js` temporário a partir da fixture; o único insumo externo que resta é o `5_Calculadora_Final/app.js` (oráculo, não copiado).

Notas da 1.1: `config.py` reúne todos os erros de uma vez (`ConfigInvalida`), valida catálogo/schema/tabela como identificadores simples (entram no SQL), oculta host, `http_path` e segredos do `repr`/`resumo()`, e assume `GN_AUTH_TIPO` = `pat` em dev e `oauth_m2m` em HML/PRD. Acrescentada a variável `GN_ARQUIVO_JSON` (obrigatória com `GN_FONTE=json`), não prevista na seção 5. `.gitignore` agora cobre `.env` e `.cache/`. `app.py` ainda não consome a config (1.5/1.6). Execução local com `.env`: o código lê só `os.environ` (sem python-dotenv); documentar na 1.8 (`set -a; . ./.env; set +a`) ou decidir adotar python-dotenv.

## 1. Resumo

Manter a lógica do site (filtros, cálculo, formatação, templates) e trocar **apenas a origem dos dados**: de `data/tarifas.json` (gerado por script manual) para a tabela Gold `fct_gn_tarifa_vigente_calculadora`, lida no Databricks por SQL Warehouse, com cache em memória e cópia local para tolerar indisponibilidade.

Decisões já tomadas (ADR 0003 da `9_ETL`, mais as suas respostas):

| Tema | Decisão |
|---|---|
| Base de código | Copiar `6_Calculadora_Flask` para `10_Calculadora_Flask`. A `6` não é alterada |
| Fonte de dados | Gold `fct_gn_tarifa_vigente_calculadora` (+ `fct_gn_parametro_vigente_calculadora` em fase posterior) |
| Schemas | DEV `marketing_dev.dbt_guilherme_oliveira` · HML `marketing_hml.marketing_gold` · PRD `marketing_prd.marketing_gold` |
| Cache | Mart inteiro (~500 linhas) em memória, recarga periódica, cópia JSON local atômica como fallback |
| Conexão | **Fase 1: como se não houvesse Kubernetes** (máquina local/Docker, tudo por variáveis de ambiente). **Fase 2: preparar** a troca para Kubernetes sem mexer no código |

## 2. Achados da análise (divergências com o enunciado)

1. **A `8_pipeline_calculadora_gn` não contém o site.** É a ingestão (extratores, Volume Bronze, job Databricks). O site Flask está na `6_Calculadora_Flask`. Confirmado por você: a base é a `6`. A `8` serve só de referência de config Databricks/`.env`.
2. **A `9_ETL_calculadora_gn` (pasta do usuário) tem só documentação.** O projeto dbt completo, com os modelos `*_gn_*`, está em `/Workspace/Shared/IA - Calculadora GN/ETL_calculadora_gn` (espelho do `D:\DEV\DBT_MARKETING`, que não é acessível deste ambiente). O contrato foi lido de lá.
3. **Schema DEV divergente nos docs:** a `9` e a `8` citam `dev_guilherme_oliveira`; vale `dbt_guilherme_oliveira` (sua resposta). Os docs da `9` devem ser corrigidos, fora do escopo deste plano.
4. **O contrato tem 23 colunas, não 22** (17 antigas + `deliberacao`, `vigencia_inicio`, `atualizado_em`, `status_atualizacao`, `origem_valor` + `grupo_tarifario_key`). Os docs dizem "17 + 5".
5. **A Gold entrega tarifa líquida** (`preco_concessionaria = 'sem impostos'`, decisão de 2026-10-21). O `calculo.py` já funciona assim (`aliquotas_da_publicacao` devolve 0), mas **os resultados deixam de bater com o `tarifas.json` de 2026-09-03** em alguns grupos (B-05, P-02 Consumo mínimo, tarifas reais atualizadas). O teste de paridade com `app.js` precisa ser reposicionado (seção 6).
6. **Parâmetros hoje fixos em `calculo.py`:** `FATOR_GN_PARA_GLP`, `FATOR_GLP_PARA_GN` e `ALIQUOTA_MONOFASICA_GLP = 1.6377` (= 1,47 ICMS + 0,1677 PIS/Cofins, muda todo 1º de janeiro). A tabela `fct_gn_parametro_vigente_calculadora` só expõe os dois fatores (`usado_na_calculadora = true`); a monofásica está `false`. Ver pendência D-03.
7. **Docs atuais falam em AlmaLinux/systemd/`AtualizarDados.sh`.** Tudo isso sai: não há mais arquivo manual.
8. **A imagem Docker atual copia `4_Mapa_GN` da raiz do projeto**, o que amarra o build ao diretório pai. Ver D-02.

## 3. Arquitetura alvo

```
Databricks (Unity Catalog)               Flask (10_Calculadora_Flask)
┌─────────────────────────┐   HTTPS 443   ┌──────────────────────────────────────────┐
│ SQL Warehouse           │◄──────────────│ calculadora/fonte_databricks.py          │
│ <catalogo>.<schema>.    │  SELECT *     │   └ credenciais.py (pat | oauth_m2m | u2m)│
│  fct_gn_tarifa_vigente_ │               │ calculadora/dados.py                     │
│  calculadora            │               │   Repositorio: memória + TTL + validação │
└─────────────────────────┘               │   └ cache_local.py (JSON atômico)        │
                                          │ calculo / filtros / formatacao (iguais)  │
                                          │ app.py: /, /api/*, /saude, /saude/pronto │
                                          └──────────────────────────────────────────┘
```

Princípio: **a tela nunca espera o Databricks.** A carga roda no início e em thread de segundo plano a cada N minutos (o SQL Warehouse pode levar minutos para ligar). Requisições sempre usam a última base válida em memória.

### 3.1 Comportamento de carga

| Situação | Resultado |
|---|---|
| Partida, Databricks ok | Carrega, valida, grava cópia local, passa a `origem = databricks` |
| Partida, Databricks fora, cópia local válida | Usa a cópia, `origem = cache_local`, loga alerta |
| Partida, sem Databricks e sem cópia | `/saude/pronto` falha e a tela mostra 503 |
| Recarga ok | Troca a base em memória de forma atômica |
| Recarga falha (rede, auth, warehouse) | Mantém a base atual, registra a falha e o tempo desde a última carga ok |
| Recarga traz base **inválida** | **Descarta e mantém a última válida**, erro em log (base inválida nunca calcula, ADR 0003). Muda em relação ao `dados.py` de hoje, que passa a dar 503 |
| Base em memória velha demais (`GN_BASE_MAX_IDADE_HORAS`, padrão 72) | Continua calculando, mas a tela mostra aviso e `/saude` marca `degradado` |

### 3.2 Camada de conexão preparada para Kubernetes

Para quem não conhece Kubernetes: um *pod* é só o contêiner Docker rodando. Para falar com o Databricks, ele faz uma **chamada HTTPS de saída (porta 443)** ao host do workspace, igual ao que sua máquina faz. Não há "conexão especial". O que muda no Kubernetes são quatro coisas, todas externas ao código:

| Tema | Local / Docker | Kubernetes |
|---|---|---|
| Credenciais | arquivo `.env` | `Secret` injetado como variáveis de ambiente |
| Configuração | `.env` | `ConfigMap` (host, http_path, ambiente, TTL) |
| Rede | sai pela rede da sua máquina | **egress** do cluster precisa alcançar o host do workspace (firewall, proxy corporativo, DNS, Private Link). Pode exigir liberar o IP de saída do cluster na *IP access list* do workspace |
| Cache local | pasta do projeto | `emptyDir` (efêmero; o pod também sobrevive a restart pela primeira carga online) |

Por isso o código segue só estas regras, e a troca de ambiente é só mudar variáveis:
- **Nada de caminho, host ou segredo fixo**; tudo via variável de ambiente (`GN_*`, `DATABRICKS_*`).
- **Autenticação plugável** (`GN_AUTH_TIPO`): `pat` (token, só dev), `oauth_m2m` (service principal, HML/PRD e Kubernetes), `oauth_u2m` (login no navegador, dev local).
- **Suporte a proxy** por `HTTPS_PROXY`/`NO_PROXY` (já respeitado pela biblioteca de HTTP).
- **Probes separados:** `/saude` (liveness, só diz que o processo vive, **não** consulta Databricks, para uma queda do Databricks não reiniciar pods) e `/saude/pronto` (readiness, exige base válida em memória).
- **Log em stdout** e processo sem estado persistente.
- Manifests Kubernetes entregues como **modelo** em `deploy/k8s/`, sem aplicar nada.

## 4. Mapa de alterações

### 4.1 Copiar sem mudança (paridade de comportamento)
`calculadora/calculo.py`, `filtros.py`, `formatacao.py`, `templates/index.html`, `templates/erro.html`, `static/css/calculadora.css`, `static/js/*`, `static/assets/*`. Pequenos ajustes de template apenas na seção 4.3.

### 4.2 Novos
| Arquivo | Função |
|---|---|
| `calculadora/config.py` | Lê e valida variáveis de ambiente; resolve `catalogo.schema.tabela` pelo ambiente (`dev`/`hml`/`prd`) com override por `GN_CATALOGO`/`GN_SCHEMA` |
| `calculadora/credenciais.py` | Estratégias de autenticação (`pat`, `oauth_m2m`, `oauth_u2m`) atrás de uma interface única |
| `calculadora/fonte.py` | Protocolo `FonteDados.carregar() -> payload` |
| `calculadora/fonte_databricks.py` | Implementação com `databricks-sql-connector`: `SELECT` explícito das 23 colunas, `ORDER BY`, timeout, conversões `Decimal→float`, `date→str ISO` |
| `calculadora/fonte_json.py` | Implementação que lê JSON (fixtures de teste e desenvolvimento offline). Substitui o antigo caminho de produção |
| `calculadora/cache_local.py` | Cópia JSON atômica (arquivo temporário + `os.replace`) com metadados de origem e data |
| `deploy/k8s/*.yaml` | Modelos de Deployment, Service, ConfigMap, Secret (sem valores), probes |
| `.env.example` | Todas as variáveis, sem segredos |
| `scripts/testar_conexao.py` | Diagnóstico: DNS, TCP 443, autenticação, `SELECT 1`, permissão na tabela e contagem de linhas (cobre a task 2.10.01 e a pendência G5 da `9`) |

### 4.3 Alterados
| Arquivo | Mudança |
|---|---|
| `calculadora/dados.py` | `RepositorioTarifas` passa a orquestrar fonte + cache + recarga em segundo plano + validação. `validar_registros` ganha: tipos novos (`status_atualizacao`, `origem_valor`, `atualizado_em`), valores aceitos, nulos permitidos em `deliberacao`/`vigencia_inicio`/`dt_delib`; mantém as regras atuais |
| `app.py` | `create_app` recebe a fonte; novas rotas `/saude/pronto`; `/saude` ampliado (origem, `carregado_em`, idade, `generated_at`, contagem); o `waitress` e a variável `PORTA` continuam |
| `templates/index.html`, `_resultados.html` | Aviso discreto quando `status_atualizacao = desatualizada` ou `origem_valor` ≠ `execucao_atual`, e exibir `atualizado_em`/`vigencia_inicio` (requisito do plano da `9`, item 4) |
| `requirements.txt` | Adiciona `databricks-sql-connector` (versão a fixar na instalação) e dependência de `pyarrow` se exigida |
| `Dockerfile` | Sem `COPY data/` nem montagem de volume; usuário sem privilégio; cache em `/tmp/gn_cache` (ou `GN_CACHE_PATH`); build independente do diretório pai (ver D-02) |
| `docker-compose.yml` | `env_file: .env`, sem `volumes: ./data`, nome de serviço próprio; só para dev/teste |
| `tests/test_app.py` | Rotas e contexto recriados com `FonteJson` e uma fonte falsa |
| `tests/test_paridade_js.py` | Passa a usar a fixture congelada (seção 6) |

### 4.4 Removidos (não copiados)
`Iniciar_Calculadora.bat`, `Iniciar_Calculadora.sh`, `Iniciar_Calculadora_Docker.sh` (substituídos por um `Makefile`/scripts simples), `deploy/calculadora-gn.service` (systemd), `migracao.md` (vira histórico), qualquer dependência de `AtualizarDados.sh` e de `3_Manutencao/atualizar_calculadora.py`, `data/tarifas.json` como fonte (vira `tests/fixtures/`).

## 5. Variáveis de ambiente (contrato inicial)

| Variável | Padrão | Uso |
|---|---|---|
| `GN_AMBIENTE` | `dev` | Resolve catálogo/schema: dev→`marketing_dev.dbt_guilherme_oliveira`, hml→`marketing_hml.marketing_gold`, prd→`marketing_prd.marketing_gold` |
| `GN_CATALOGO`, `GN_SCHEMA` | — | Override explícito |
| `GN_TABELA_TARIFAS` | `fct_gn_tarifa_vigente_calculadora` | Nome da tabela |
| `GN_FONTE` | `databricks` | `databricks` ou `json` (offline/testes) |
| `GN_ARQUIVO_JSON` | — | Caminho do JSON; obrigatória com `GN_FONTE=json` |
| `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH` | — | Workspace e SQL Warehouse |
| `GN_AUTH_TIPO` | `pat` em dev | `pat` / `oauth_m2m` / `oauth_u2m` |
| `DATABRICKS_TOKEN` | — | Somente `pat` |
| `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET` | — | Somente `oauth_m2m` |
| `GN_RECARGA_MINUTOS` | `30` | Intervalo de recarga (a Gold muda 1x/dia após as 06:00) |
| `GN_TIMEOUT_CONSULTA_S` | `60` | Timeout da consulta |
| `GN_CACHE_PATH` | `./.cache/tarifas.json` | Cópia local |
| `GN_BASE_MAX_IDADE_HORAS` | `72` | Limite do aviso de base antiga |
| `HOST`, `PORTA`, `FLASK_DEBUG`, `TZ` | como hoje | Servidor |

Segredos **nunca** entram em imagem, repositório ou log.

## 6. Estratégia de testes

1. **Fixture congelada:** `tests/fixtures/tarifas_2026-09-03.json` (a base atual). O teste de paridade com `app.js` roda sobre ela, porque a lógica de cálculo não muda. Isso prova que a troca de fonte não alterou o motor.
2. **Contrato da Gold:** teste que valida o payload de 23 colunas (tipos, nulos, valores aceitos) e que `dados.validar_registros` aceita a saída da fonte Databricks simulada (`Decimal`, `date`).
3. **Cenários do repositório** com fonte falsa: carga ok; Databricks fora com cópia; sem cópia (503); recarga inválida mantém a última válida; recarga atualiza; base antiga gera aviso; escrita atômica (sem arquivo pela metade).
4. **Rotas:** `/`, `/api/calcular`, `/api/tarifas`, `/saude`, `/saude/pronto`.
5. **Integração real** (`pytest -m databricks`, ignorado sem variáveis): `SELECT` na Gold dev, confere 23 colunas e que `validar_registros` passa.
6. **Conferência de dados Gold × base atual** (cobre a task 2.8.01 da `9`): relatório de diferenças por grupo, cada uma classificada (correção esperada, mudança real de tarifa ou bug). O resultado define o aceite de HML.
7. **Teste manual guiado** em HML com a IM (P-10/P-11: MS, RS, SE, CE).

## 7. Fases e tarefas

### Fase 0: Alinhamento e fundação (0,5 a 1 dia)
| ID | Tarefa | Pronto quando |
|---|---|---|
| 0.1 | Resolver as pendências D-01 a D-05 (seção 9) | Respostas registradas |
| 0.2 | Criar a estrutura `10_Calculadora_Flask` copiando a `6` (sem os itens da 4.4) | `pytest` da cópia passa tal como na `6` |
| 0.3 | Congelar `tests/fixtures/tarifas_2026-09-03.json` | Paridade com `app.js` ainda verde |

### Fase 1: Leitura da Gold, "como se não houvesse Kubernetes" (2 a 3 dias)
| ID | Tarefa | Pronto quando |
|---|---|---|
| 1.1 | `config.py` + `.env.example` + resolução de ambiente | Testes de config; erro claro para variável ausente |
| 1.2 | `credenciais.py` (`pat`, `oauth_u2m`, `oauth_m2m`) | Conexão em dev com `pat` ou `oauth_u2m` |
| 1.3 | `scripts/testar_conexao.py` | Roda em dev e aponta a camada que falhou |
| 1.4 | `fonte_databricks.py` + conversões de tipo | `SELECT` real na tabela dev devolve 23 colunas e passa na validação |
| 1.5 | `cache_local.py` + `RepositorioTarifas` (recarga em segundo plano, fallback, descarte de base inválida) | Cenários da 6.3 verdes |
| 1.6 | `app.py`: rotas `/saude` e `/saude/pronto`; ajustes de `index.html` para status/origem/atualização | `/saude` mostra a origem; aviso aparece com dado de teste desatualizado |
| 1.7 | Testes (6.1 a 6.5) e conferência Gold × base atual (6.6) em DEV | Relatório sem diferença "não explicada" |
| 1.8 | Docs da fase: `README`, `CONFIGURACAO`, `CONTRATO_DADOS` | Alguém sem contexto sobe a app em DEV seguindo só o README |

### Fase 2: Pronto para Kubernetes (1 a 2 dias, depende de infra)
| ID | Tarefa | Pronto quando |
|---|---|---|
| 2.1 | Dockerfile final (usuário não root, sem volume de dados, healthcheck) e `docker-compose` de teste | Imagem sobe com `.env` e lê a Gold dev |
| 2.2 | Service principal `oauth_m2m` em HML (com Infra/Governança; `SELECT` só nas 2 tabelas, `USE CATALOG/SCHEMA`, `CAN USE` no warehouse, task 2.9.03 da `9`) | `testar_conexao.py` ok em HML e **nega** leitura de outra tabela |
| 2.3 | Validar rede do cluster até o workspace (DNS, egress 443, proxy, IP access list, Private Link) com `testar_conexao.py` dentro de um pod de teste | Script passa de dentro do cluster. Fecha G5 |
| 2.4 | Manifests modelo `deploy/k8s/` (Deployment, Service, ConfigMap, Secret vazio, probes, `emptyDir`, recursos, `replicas`) | `kubectl apply --dry-run=client` ok |
| 2.5 | Docs: `KUBERNETES.md` (guia para iniciantes), `RUNBOOK`, `ARQUITETURA`, ADRs | Revisão pelo time |

### Fase 3: Homologação e produção (2 a 3 dias + validação IM)
| ID | Tarefa | Pronto quando |
|---|---|---|
| 3.1 | Deploy HML apontando `marketing_hml.marketing_gold` | `/saude/pronto` ok, comparação com PRD atual |
| 3.2 | Validação com a IM (cenários P-10/P-11) | Aceite registrado |
| 3.3 | Teste de falha em HML: derrubar warehouse, rotacionar segredo, tabela vazia | Comportamentos da 3.1 confirmados e RUNBOOK ajustado |
| 3.4 | Deploy PRD com `marketing_prd.marketing_gold`; desligar o fluxo manual (`AtualizarDados.sh`) | Primeiro dia com recarga automática ok |
| 3.5 | Alertas: `/saude` degradado, base antiga, falha de recarga | Responsável e canal definidos |

### Fase 4: Evolução (opcional, depois do go-live)
- Ler `fct_gn_parametro_vigente_calculadora` para os fatores GN↔GLP e, se a dbt a expuser, a monofásica (D-03).
- Endpoint administrativo para forçar recarga (protegido).
- Observabilidade (métricas de carga, idade da base).

## 8. Documentação a produzir em `10_Calculadora_Flask`

| Documento | Conteúdo |
|---|---|
| `README.md` | O que é, como rodar em DEV, testes, estrutura, rotas |
| `docs/RUNBOOK.md` | Operação: checagens diárias, runbooks por cenário (Databricks fora, token/secret expirado ou rotacionado, warehouse frio, base inválida, base desatualizada, sem permissão, rollback de imagem, falha de rede no cluster), comandos e contatos |
| `docs/ARQUITETURA.md` | Diagramas, fluxo de carga, decisões |
| `docs/CONTRATO_DADOS.md` | As 23 colunas, tipos, nulos, regras de validação, relação com a `9` |
| `docs/CONFIGURACAO.md` | Variáveis de ambiente por ambiente |
| `docs/KUBERNETES.md` | Guia para quem nunca usou, o que muda na conexão, checklist de infra |
| `docs/adr/` | 0001 fonte plugável e cache; 0002 autenticação e service principal; 0003 probes e falha segura |
| `docs/MIGRACAO_DA_6.md` | O que mudou da `6`, para historicidade |

## 9. Pendências e riscos

| ID | Pendência | Proposta provisória |
|---|---|---|
| D-01 | **Decidido:** autenticação por PAT em DEV e service principal (`oauth_m2m`) em HML/PRD. `oauth_u2m` fica opcional | Host, `http_path` e warehouse de DEV ainda precisam ser informados |
| D-02 | **Decidido:** copiar `4_Mapa_GN` para `10_Calculadora_Flask/mapa/` | Build independente do diretório pai |
| D-03 | **Validado no código dbt:** `fct_gn_parametro_vigente_calculadora` expõe só `FATOR_GN_PARA_GLP` e `FATOR_GLP_PARA_GN` (`usado_na_calculadora = true`). A alíquota monofásica existe no seed, mas com `usado_na_calculadora = false`, então não chega à Gold | Fase 1 mantém as constantes no código. Na Fase 4, pedir à dbt que marque a monofásica (ICMS 1,47 + PIS/Cofins 0,1677 = 1,6377) e confirmar na tabela real em DEV com `SELECT` |
| D-04 | **Decidido:** time de infra entrega service principal e rede em cerca de 2 semanas | Fases 0 e 1 seguem com PAT em DEV; Fase 2 (itens 2.2 e 2.3) e Fase 3 aguardam a infra |
| D-05 | Quantas réplicas e se o cache local precisa ser compartilhado | Cada réplica tem cache próprio, sem estado compartilhado; 2 réplicas bastam |
| R-1 | Warehouse frio atrasa a carga | Recarga em segundo plano; a tela usa a base em memória |
| R-2 | Mudança de tarifa/regra entre a base manual e a Gold altera resultados | Conferência Gold × base atual, explicada antes do go-live |
| R-3 | Pendências de regra de negócio com a IM (P-01 a P-11, sobretudo P-02 Consumo mínimo e P-06 grupos AM/PR) | Fora do escopo do site; o site só reflete a Gold |
| R-4 | Rotação de segredo derruba a conexão | RUNBOOK + alerta de recarga falhando; cópia mantém o site de pé |
| R-5 | Compatibilidade `databricks-sql-connector`/`pyarrow` com Python 3.12 slim | Fixar versões na Fase 1.4 e testar a imagem |

## 10. Critérios de aceite do projeto

1. O site sobe em DEV, HML e PRD só mudando variáveis de ambiente.
2. Nenhum arquivo de tarifa manual participa do fluxo.
3. Com o Databricks fora, o site continua calculando com a última base válida e mostra o estado em `/saude`.
4. Base inválida nunca é usada para calcular.
5. Resultados dos 3.040 cenários continuam idênticos aos do `app.js` sobre a fixture congelada. Diferenças da Gold atual estão explicadas.
6. README e RUNBOOK permitem que uma pessoa nova opere o serviço.
7. Credenciais fora de código, imagem e log, com permissão mínima.
