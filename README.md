# Calculadora GLP x GN — versão Python (Flask)

Mesma tela e mesmos resultados da `5_Calculadora_Final`, mas agora **filtros, cálculo,
formatação e montagem das tabelas rodam em Python**. O navegador só envia as
premissas escolhidas e mostra o HTML devolvido pelo servidor.

> **Repositório oficial da calculadora.** Veio da pasta `6_Calculadora_Flask` do repositório
> `IA - Calculadora GN` (Azure DevOps, projeto Hub_IA), importada em 29/10/2026 com o histórico
> dela. A raiz deste repositório corresponde àquela pasta. Mudanças na calculadora são feitas
> aqui; o repositório do Azure DevOps fica só como referência. Documentos antigos
> ([migracao.md](migracao.md), [migracao_etl.md](migracao_etl.md), [processo_im/](processo_im/LEIA-ME.md))
> ainda citam `6_Calculadora_Flask/`: leia como a raiz deste repositório.

## Como usar

Dê dois cliques em **`Iniciar_Calculadora.bat`**. Na primeira execução, ele cria o
ambiente Python (`.venv`) e instala as dependências. Depois inicia o servidor e abre
http://127.0.0.1:5000 no navegador. Para encerrar, feche a janela preta (ou use Ctrl+C).

Pelo terminal:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python app.py
```

Variáveis opcionais: `PORTA` (padrão 5000), `HOST=0.0.0.0` (para abrir na rede
interna), `FLASK_DEBUG=1` (servidor de desenvolvimento com recarga automática) e
`TARIFAS_GN_JSON` (caminho alternativo da base).

### Servidor Linux (AlmaLinux)

```bash
sudo dnf install -y python3.11 hostname git
sudo git clone https://github.com/GuiOliveiraCOPA/im-calculadora-gn.git /opt/calculadora-gn
cd /opt/calculadora-gn
chmod +x Iniciar_Calculadora.sh
./Iniciar_Calculadora.sh            # 0.0.0.0:5000; cria o .venv na primeira vez
./Iniciar_Calculadora.sh --testar   # roda os testes
```

No Linux, o script escuta em `0.0.0.0` por padrão (use `HOST=127.0.0.1` se ficar atrás
de um nginx). Para liberar a porta no firewall:

```bash
sudo firewall-cmd --permanent --add-port=5000/tcp && sudo firewall-cmd --reload
```

Para rodar como serviço permanente, que reinicia sozinho e sobe junto com o servidor, use
[deploy/calculadora-gn.service](deploy/calculadora-gn.service). As instruções estão no
cabeçalho do arquivo.

### Em contêiner (Docker ou Podman) — recomendado para o servidor

```bash
cd /opt/calculadora-gn
chmod +x Iniciar_Calculadora_Docker.sh
./Iniciar_Calculadora_Docker.sh              # roda os testes, constrói e sobe na porta 5000
PORTA=8080 ./Iniciar_Calculadora_Docker.sh   # outra porta
./Iniciar_Calculadora_Docker.sh --logs       # acompanha os logs
./Iniciar_Calculadora_Docker.sh --parar      # derruba
```

O script usa o Docker (`docker compose`) ou o Podman (`podman compose`/`podman-compose`), o que
estiver instalado. No AlmaLinux: `sudo dnf install -y podman podman-compose`.

- **A imagem leva o código, o processo do IM e o mapa** (tudo neste repositório, cuja raiz é o
  contexto do build). Ela inclui as bibliotecas dos extratores e o Chromium usado pelo Selenium.
- **O ETL roda dentro do contêiner**, todo dia às 00:00 (horário de Brasília). Veja a seção
  [ETL da base tarifária](#etl-da-base-tarifária).
- **O estado fica em volumes** (`tarifas`, `planilhas_uf`, `passado_tarifas`, `planilha_final`,
  `execucoes_cmd`): base publicada, agendamento, histórico, planilhas por UF, histórico de tarifas
  e logs sobrevivem a reinícios e a novas versões da imagem. Na primeira subida, o Docker e o
  Podman preenchem cada volume vazio com o conteúdo da imagem (por exemplo, o `tarifas.json`
  versionado). Depois disso vale o conteúdo do volume: uma imagem nova **não** substitui a base
  que já está nele. Em Kubernetes, volumes persistentes (PVC) **não** são preenchidos com o
  conteúdo da imagem: montados por cima de `/app/data` e das pastas do processo, eles escondem
  os arquivos da imagem e começam vazios, a menos que algo os copie antes (por exemplo, um
  initContainer).
- **A base manual `Tarifario_GN.xlsx`** vem da pasta do servidor
  (`processo_im/2_Bases_Origem`, montada só para leitura): basta trocar o arquivo, sem reconstruir.
- Quando o ETL publica um `tarifas.json` novo, a calculadora carrega sozinha em segundos,
  **sem reiniciar o contêiner**. Base inválida → página de erro (503), nunca cálculo errado.
- **Reinicia sozinho** com o servidor (`restart: unless-stopped`) e tem checagem de saúde em `/saude`.
- Roda como usuário sem privilégio, no horário de Brasília.
- Os testes rodam no estágio `teste` da imagem. O `Iniciar_Calculadora_Docker.sh`/`.bat` constrói
  esse estágio antes de subir: se os testes falharem, a imagem nova não sobe. Um
  `docker compose up --build` ou `docker build` direto constrói só o estágio `final` e **não roda
  os testes**; num pipeline de CI, rode antes `docker build --target teste .`.

Com o contêiner, o `deploy/calculadora-gn.service` (systemd) não é necessário.

## ETL da base tarifária

Resumo da migração, testes e pontos de atenção: [migracao_etl.md](migracao_etl.md).

O processo de coleta e tratamento do IM foi migrado **sem alterações** para
[`processo_im/`](processo_im/LEIA-ME.md) (cópia de `1_Processo_Extracao_Dados`, `2_Bases_Origem`,
`3_Manutencao` e `4_Mapa_GN`). O pacote `etl/` só orquestra a execução, no mesmo roteiro do
`AtualizarDados.sh`:

1. **Extração e consolidação:** `Fonte_Dados/codigo_central.py` roda os 17 extratores e gera a
   `Planilha_GN_Atualizada.xlsx`.
2. **Base da calculadora:** `3_Manutencao/atualizar_calculadora.py` cruza a planilha com o
   `Tarifario_GN.xlsx`. Só roda se a etapa 1 terminar sem erro (como no `.sh`), a menos que se
   marque "atualizar mesmo com erro".
3. **Validação e publicação:** o `tarifas.json` gerado passa pela validação de
   `calculadora/dados.py` e só então substitui `data/tarifas.json` (troca atômica). Se falhar,
   a calculadora continua com a base anterior.

**Tela interna: `/interno/etl`** (sem link no site). Nela é possível:

- executar o ETL manualmente (todas as UFs ou só algumas; opção de não acessar os sites);
- ver e alterar o agendamento (horário e dias da semana; padrão: todo dia às 00:00);
- acompanhar a execução ao vivo (etapa, status por UF e log);
- ver o histórico (sucesso / parcial / erro, se a base foi publicada, registros, UFs com falha);
- ler e baixar os logs de `Execucoes_CMD` e baixar a `Planilha_GN_Atualizada.xlsx`;
- conferir a base que a calculadora está usando (data de geração, registros, validação).

Defina **`ETL_SENHA`** no servidor para a tela pedir senha (autenticação básica; qualquer usuário).
Sem ela, a tela fica só oculta e **qualquer pessoa que souber o endereço pode disparar o ETL**.

### Onde configurar as senhas (`ETL_SENHA` e `SECRET_KEY`)

São variáveis de ambiente. **Nunca** coloque os valores no código nem no git.

- **Docker Compose:** arquivo `.env` ao lado do `docker-compose.yml` (já está no `.gitignore`):
  ```
  ETL_SENHA=uma-senha-forte
  SECRET_KEY=uma-chave-aleatoria-longa
  ```
- **Kubernetes:** um `Secret` com as duas chaves, lido no `Deployment` por `env[].valueFrom.secretKeyRef`
  (ou sincronizado do Azure Key Vault, se a infra usar).

Defina também a `SECRET_KEY`: sem ela, cada início do servidor gera uma chave nova.

| Variável | Padrão | Uso |
|---|---|---|
| `ETL_AGENDADOR` | `1` no Docker; desligado fora dele | Liga o agendamento dentro do servidor |
| `ETL_SENHA` | vazia | Senha da tela `/interno/etl` |
| `ETL_PROCESSO_DIR` | `processo_im/` | Pasta do processo do IM |
| `ETL_ESTADO_DIR` | `data/etl/` | Agendamento, histórico e saída temporária |
| `ETL_PYTHON` | o Python do servidor | Interpretador com as bibliotecas dos extratores |
| `SECRET_KEY` | aleatória a cada início | Assinatura das mensagens da tela |

Pelo terminal (mesmo roteiro e mesmo log):

```bash
python -m etl                       # todas as UFs
python -m etl --only SP,RJ
python -m etl --skip-run            # não acessa os sites; reaproveita as planilhas por UF
docker exec calculadora-gn python -m etl
```

As planilhas por UF (`Fonte_Dados/PlanilhasUf/`) são geradas pelos extratores e **não estão no
git**. Num servidor novo, elas só existem depois da primeira execução completa. Até lá, o
`--skip-run` termina com "sem excel" nas UFs, e um extrator que falhar não tem planilha anterior
para usar no lugar.

O agendador confere o horário a cada 30 segundos. Se o servidor estiver desligado no horário, a
execução não é recuperada depois; rode manualmente pela tela. Só uma execução roda por vez.

## Como a correção dos dados é garantida

1. **Validação ao carregar** (`calculadora/dados.py`). Cada registro precisa ter textos e
   números válidos, `faixa_min ≤ faixa_max`, alíquotas entre 0 e 1 e `cascata` true/false.
   Se a base vier com problema, a calculadora mostra uma página de erro (HTTP 503) em vez
   de calcular com dados errados.
2. **Escrita atômica** do `tarifas.json`, para o servidor nunca ler um arquivo pela metade.
3. **Escape automático** (Jinja) de todo texto vindo da planilha.
4. **Teste de paridade** (`tests/test_paridade_js.py`). Executa o `app.js` original em
   Node.js e compara, texto a texto, com a saída do Python: 3.040 cenários de cálculo
   (todas as combinações da base × 19 volumes × GLP/GN) e 1.995 combinações de filtros.
5. **Testes unitários** (`tests/test_app.py`) para regras de imposto, cascata, conversão,
   formatação pt-BR, validação e rotas.

```bat
.venv\Scripts\python -m pytest
```

Rode os testes sempre que alterar uma regra de cálculo. Se a regra mudar de propósito,
a versão `5_Calculadora_Final\app.js` deixa de ser a referência, e o teste de paridade
deve ser ajustado ou aposentado.

A `5_Calculadora_Final` não está neste repositório (fica no repositório do Azure DevOps). Sem ela
ao lado da pasta do projeto, ou sem Node.js, os 2 testes de paridade são **pulados**.

## Checks antes de publicar uma mudança

```bash
python -m pytest                                        # 52 aprovados, 2 pulados (paridade)
ruff check --isolated --select E9,F63,F7,F82,F811 .     # erros reais: sintaxe, nome indefinido etc.
python -m mypy --ignore-missing-imports app.py calculadora etl
```

Para conferir as etapas 2 e 3 do ETL sem acessar os sites, gere a base a partir da planilha
consolidada versionada e compare com a publicada (deve dar 0 diferenças):

```bash
python etl/rodar_atualizar_calculadora.py processo_im/3_Manutencao /tmp/saida.json /tmp/saida.js
```

Validação feita em 29/10/2026 (Python 3.12, todas as dependências): 52 testes aprovados; 36
arquivos `.py` compilam; nenhum erro real no `ruff`; o `mypy` só aponta anotações de tipo (sem
erro em execução); a base gerada pela planilha versionada é idêntica ao `data/tarifas.json`
(459 registros).

### Pontos de atenção conhecidos (comportamento do processo do IM, confirmados em teste)

- **"Atualizar mesmo com erro" pode voltar tarifas antigas.** O `atualizar_calculadora.py` parte
  sempre do `Tarifario_GN.xlsx` e só sobrescreve as UFs que vieram na extração. UF que falhar
  **e** não tiver planilha anterior em `PlanilhasUf/` volta ao valor do `Tarifario_GN.xlsx`, e a
  validação aprova (o formato está certo). Num teste sem nenhuma planilha, 282 dos 459 registros
  mudaram. Em servidor novo, só use essa opção depois da primeira execução completa.
- **Execução com erro sobrescreve a `Planilha_GN_Atualizada.xlsx`** com a consolidação daquela
  execução, mesmo quando a base da calculadora não é publicada.
- **Status `excel antigo`** (extrator terminou sem gerar planilha nova) não conta como erro: a
  execução pode sair `sucesso` com a planilha anterior daquela UF.
- **Dependências do processo sem versão fixa** (`processo_im/.../Fonte_Dados/requirements.txt`).
  Cada build da imagem pode instalar versões novas. Em 29/10/2026 instalou pandas 3.1 e
  PyMuPDF 2.0 (que já avisa que o `import fitz` será removido).

## Estrutura

```
app.py                     rotas Flask
calculadora/
  dados.py                 carga, validação e recarga da base
  filtros.py               filtros em cascata (UF → segmento → concessionária)
  calculo.py               regras de cálculo (com/sem cascata, impostos, GLP↔GN)
  formatacao.py            números e moeda no padrão pt-BR
templates/
  index.html               página
  _resultados.html         área de resultados (reaproveitada pela API)
static/
  css/calculadora.css      estilo (idêntico ao original)
  js/calculadora.js        integração da tela com a API (sem regra de negócio)
  js/premissas.js          balão de premissas
etl/
  executor.py              roteiro do ETL (mesmas etapas do AtualizarDados.sh), log e histórico
  agendamento.py           agendamento diário e agendador
  rotas.py                 tela /interno/etl
  rodar_atualizar_calculadora.py  roda o atualizar_calculadora.py do IM com a saída redirecionada
processo_im/               processo de coleta e tratamento do IM, sem alterações (ver LEIA-ME.md)
data/tarifas.json          base tarifária
```

## Rotas

| Rota | Uso |
|---|---|
| `/` | Calculadora. Aceita `?uf=&segmento_copa=&concessionaria=&tipo_entrada=glp\|gn&volume=` e funciona até sem JavaScript |
| `/api/calcular` | Mesmos parâmetros. Devolve filtros, valores numéricos e o HTML dos resultados |
| `/api/tarifas` | Base tarifária carregada |
| `/saude` | Status e data de geração da base |
| `/mapa/` | Mapa de GN (servido da pasta `processo_im/4_Mapa_GN`) |
| `/interno/etl/` | Tela interna do ETL (sem link no site) |

## Diferença intencional em relação ao original

Quando não há tarifa para a combinação (ou o volume é inválido), o `app.js` deixava na
tela os cabeçalhos "PIS/Cofins (R$ | x%)" e o texto de faixas do cálculo anterior. Esta
versão volta aos textos padrão.
