# Migração do ETL do IM para a Calculadora GLP x GN (Flask)

> **Documento histórico.** Descreve a migração como foi feita no repositório `IA - Calculadora GN`
> (Azure DevOps). Lá esta calculadora ficava na pasta `6_Calculadora_Flask`, que hoje é a raiz deste
> repositório: onde o texto diz `6_Calculadora_Flask/`, leia a raiz. Pastas citadas como
> `5_Calculadora_Final`, `1_Processo_Extracao_Dados` etc. na raiz do projeto não fazem parte deste
> repositório (as usadas pela calculadora estão em `processo_im/`). Estado atual: [README.md](README.md).

**Data:** 19/10/2026
**Origem:** processo de coleta e tratamento do time de Inteligência de Mercado (IM), que rodava
pelo `AtualizarDados.bat`/`.sh` e pelo `Atualizar_Calculadora.bat`
**Destino:** `6_Calculadora_Flask` (produto do time de dados), executado pelo Docker

## Resumo

A coleta das tarifas nos sites das distribuidoras e o tratamento que gera a base da calculadora
passaram a rodar **dentro do produto Flask**. Esta é a **versão 1**: o código do IM foi copiado
**sem nenhuma alteração ou melhoria** e reflete exatamente o processo atual do IM.

- No Docker, o ETL roda **sozinho todo dia às 00:00** (horário de Brasília).
- Há uma **tela interna, sem link no site**, para executar manualmente, ver e alterar o
  agendamento, acompanhar o log e confirmar que a base foi atualizada: **`/interno/etl`**.
- A calculadora só passa a usar uma base nova depois que ela **passa na validação**. Se algo
  falhar, continua com a base anterior.

## O que foi feito

### 1. Cópia fiel do processo do IM → `processo_im/`

| Pasta em `processo_im/` | Copiada de | Papel |
|---|---|---|
| `1_Processo_Extracao_Dados/` | `1_Processo_Extracao_Dados/` | 17 extratores (`Fonte_Dados/tabela_*.py`) e consolidação (`codigo_central.py`) |
| `2_Bases_Origem/` | `2_Bases_Origem/` | Base manual `Tarifario_GN.xlsx` (faixas, impostos, cascata) |
| `3_Manutencao/` | `3_Manutencao/` | `atualizar_calculadora.py`, que gera o `tarifas.json` |
| `4_Mapa_GN/` | `4_Mapa_GN/` | Mapa de GN, servido em `/mapa/` |

- A estrutura de pastas foi mantida porque os scripts do IM usam caminhos relativos entre elas.
- A `3_Manutencao` não estava na lista inicial, mas foi incluída: sem o `atualizar_calculadora.py`,
  a extração não chega até a calculadora.
- A cópia foi conferida arquivo por arquivo: está **idêntica** às pastas originais (exceto os
  `__pycache__`).
- As pastas originais na raiz do projeto **não foram apagadas**, mas deixam de ser a fonte usada
  pela calculadora. Correções futuras nos extratores devem ser feitas em `processo_im/`.

### 2. Orquestração → pacote `etl/` (código novo)

Faz em Python o mesmo roteiro do `AtualizarDados.sh`, chamando os scripts do IM como subprocessos:

1. **Preparação:** confere as bibliotecas e localiza o Chrome/Chromium para o Selenium.
2. **Extração e consolidação:** `Fonte_Dados/codigo_central.py` roda os 17 extratores e gera a
   `Planilha_GN_Atualizada.xlsx`.
3. **Base da calculadora:** `3_Manutencao/atualizar_calculadora.py` cruza a planilha com o
   `Tarifario_GN.xlsx`. Como no `.sh`, **só roda se a extração terminar sem erro**, a menos que
   se marque "atualizar mesmo com erro".
4. **Validação e publicação (novo):** o `tarifas.json` gerado passa pela validação da calculadora
   (`calculadora/dados.py`) e só então substitui `data/tarifas.json`, com troca atômica. A
   calculadora recarrega sozinha, sem reiniciar.

O único ponto em que o processo do IM é "ajustado" fica **fora** do código dele: o
`etl/rodar_atualizar_calculadora.py` redireciona as duas saídas do `atualizar_calculadora.py`
(que apontavam para `5_Calculadora_Final/tarifas.js` e `6_Calculadora_Flask/data/tarifas.json`
na estrutura antiga) para a área de trabalho do ETL, onde a base é validada.

| Arquivo | Responsabilidade |
|---|---|
| `etl/executor.py` | Roteiro do ETL, log, histórico, validação e publicação |
| `etl/agendamento.py` | Agendamento (horário e dias da semana) e agendador |
| `etl/rotas.py` | Tela `/interno/etl` |
| `etl/rodar_atualizar_calculadora.py` | Roda o `atualizar_calculadora.py` do IM com a saída redirecionada |
| `etl/__main__.py` | Execução pelo terminal (`python -m etl`) |
| `templates/etl.html`, `static/css/etl.css`, `static/js/etl.js` | Tela |
| `tests/test_etl.py` | 18 testes do ETL |

**Logs:** continuam em `processo_im/1_Processo_Extracao_Dados/Comece_aqui/Execucoes_CMD/`, no mesmo
padrão de nome do IM (`Execucao_NNN_AAAA-MM-DD_<responsavel>.log`). O histórico resumido de cada
execução fica em `data/etl/historico_execucoes.json`.

**Resultado de cada execução:**

| Status | Significado |
|---|---|
| `sucesso` | Todos os extratores ok; base validada e publicada |
| `parcial` | Base publicada, mas algum extrator falhou (essas UFs usaram a última planilha que funcionou) |
| `erro` | Base **não** publicada; a calculadora continua com a anterior |
| `interrompida` | O servidor foi reiniciado durante a execução |

## Tela de ETL: `/interno/etl`

Exemplo: `http://<servidor>:5000/interno/etl`. Não há link para ela no site, e ela envia
`noindex` para buscadores.

| Bloco | O que mostra / faz |
|---|---|
| Base em uso na calculadora | Se a base está válida, data de geração, registros e UFs |
| Última execução | Status, início e fim, origem (manual, agendamento ou terminal), se a base foi publicada |
| Agendamento | Regra atual, próxima execução e se o agendador está rodando no servidor |
| Execução em andamento | Etapa atual, status por UF e log ao vivo (atualiza sozinho) |
| Executar agora | Responsável, UFs (opcional), "não acessar os sites" e "atualizar mesmo com erro" |
| Alterar agendamento | Ativo/inativo, horário, dias da semana e "atualizar mesmo com erro" |
| Histórico de execuções | Últimas 30 execuções, com UFs que falharam e link para o log |
| Logs de execução | Todos os logs de `Execucoes_CMD` (inclusive os antigos do `.bat`) e download da `Planilha_GN_Atualizada.xlsx` |

- **Só uma execução por vez.** Enquanto uma roda, o botão fica desabilitado.
- **Senha:** com a variável `ETL_SENHA` definida, a tela pede usuário e senha (qualquer usuário;
  a senha é a de `ETL_SENHA`). Sem ela, a tela fica apenas oculta e mostra um aviso. **Recomendado
  definir em produção.**
- Formulários enviados a partir de outro site são recusados (HTTP 403).

## Agendamento no Docker

- O agendador é uma thread do próprio servidor da calculadora, ligada pela variável
  `ETL_AGENDADOR=1`, que **já vem definida na imagem**. Fora do Docker ele fica desligado.
- Padrão: **todo dia às 00:00**, fuso `America/Sao_Paulo`. Pode ser alterado na tela; a mudança
  vale na hora, sem reiniciar.
- O agendamento fica salvo em `data/etl/agendamento.json`, no volume `tarifas`, e sobrevive a
  reinícios.
- O horário é conferido a cada 30 segundos. Ao mudar o agendamento, a contagem recomeça a partir
  daquele momento, então um horário que já passou no dia não dispara na hora.
- Se o contêiner estiver parado no horário, **a execução não é recuperada depois**. Rode pela tela.
- Se já houver uma execução em andamento no horário, a agendada é ignorada (fica registrado no log
  do contêiner).

### Volumes do `docker-compose.yml`

| Volume / montagem | Caminho no contêiner | Conteúdo |
|---|---|---|
| `tarifas` | `/app/data` | `tarifas.json` publicado, agendamento, histórico e saída temporária do ETL |
| `planilhas_uf` | `.../Comece_aqui/Fonte_Dados/PlanilhasUf` | Planilhas por UF |
| `passado_tarifas` | `.../Comece_aqui/PassadoTarifas` | Histórico de tarifas do IM |
| `planilha_final` | `.../Comece_aqui/Planilha_Final` | `Planilha_GN_Atualizada.xlsx` |
| `execucoes_cmd` | `.../Comece_aqui/Execucoes_CMD` | Logs |
| `./processo_im/2_Bases_Origem` (só leitura) | `/app/processo_im/2_Bases_Origem` | `Tarifario_GN.xlsx`, vindo da pasta do servidor |

Na primeira subida, cada volume é preenchido com o conteúdo da imagem (base atual, planilhas,
histórico e logs do IM). Para atualizar a base manual `Tarifario_GN.xlsx`, basta trocar o arquivo
em `6_Calculadora_Flask/processo_im/2_Bases_Origem/` no servidor; não é preciso reconstruir.

### Imagem

- O contexto do build passou a ser a própria pasta `6_Calculadora_Flask` (antes era a raiz do
  projeto). Há um `.dockerignore` novo nesta pasta.
- Além do Flask, a imagem instala as bibliotecas do `requirements.txt` original do IM (sem versões
  fixas, como no original) e o `chromium` + `chromium-driver`, usados pelos extratores CE, PE, MS e MT.
- `shm_size: 1gb` no compose, para o Chromium headless.

## Como testar

### 1. Testes automáticos (Windows ou Linux)

```bat
cd 6_Calculadora_Flask
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Resultado na migração: **50 aprovados, 2 pulados** (hoje: 52 aprovados, 2 pulados) (paridade com o `app.js`, que exige Node.js). Os
testes do ETL usam um processo falso com a mesma estrutura de pastas e **não acessam os sites**.

### 2. Execução completa sem acessar os sites (recomendado antes do primeiro deploy)

Usa o código real do IM e reaproveita as planilhas já baixadas. Para não alterar os arquivos
versionados, rode numa cópia:

```bash
cp -r processo_im /tmp/teste_etl/ && cp data/tarifas.json /tmp/teste_etl/
ETL_PROCESSO_DIR=/tmp/teste_etl/processo_im TARIFAS_GN_JSON=/tmp/teste_etl/tarifas.json \
  python -m etl --skip-run --responsavel "Teste"
```

Esperado: `Status: ok` nas 17 UFs, `Base validada e publicada: 459 registros` e
`Resultado: sucesso`. Esse teste foi feito em 19/10/2026 com esse resultado.

### 3. Docker no servidor (**ainda não testado**: não havia Docker na máquina de desenvolvimento)

```bash
cd /opt/calculadora-gn/6_Calculadora_Flask
ETL_SENHA='defina-uma-senha' ./Iniciar_Calculadora_Docker.sh   # roda os testes, constrói e sobe
```

Depois, conferir:

1. `http://<servidor>:5000/` abre a calculadora e `/saude` responde `ok`.
2. `http://<servidor>:5000/interno/etl` pede a senha e mostra "Agendador: rodando neste servidor"
   e "Próxima: <amanhã> 00:00:00".
3. Rodar uma vez **sem acessar os sites** (marcar "Não acessar os sites") e conferir status `sucesso`.
4. Rodar uma vez **completa** pela tela (ou `docker exec calculadora-gn python -m etl`) e conferir
   se CE, PE, MS e MT funcionaram (eles dependem do Chromium dentro do contêiner).
5. Para testar o agendamento sem esperar a meia-noite: na tela, agendar para daqui a 2–3 minutos,
   aguardar a execução aparecer no histórico com origem `agendamento` e **voltar para 00:00**.
6. `docker compose restart` e conferir que histórico, agendamento e logs continuam lá.

## Configurações e o que precisa ser alterado

### Variáveis de ambiente

| Variável | Padrão | Uso |
|---|---|---|
| `ETL_SENHA` | vazia | Senha da tela `/interno/etl`. **Definir em produção** |
| `ETL_AGENDADOR` | `1` na imagem; desligado fora do Docker | Liga o agendamento |
| `SECRET_KEY` | aleatória a cada início | Assinatura das mensagens da tela (opcional) |
| `ETL_PROCESSO_DIR` | `processo_im/` (`/app/processo_im` no Docker) | Pasta do processo do IM |
| `ETL_ESTADO_DIR` | `data/etl/` | Agendamento, histórico e saída temporária |
| `ETL_PYTHON` | o Python do servidor | Interpretador com as bibliotecas dos extratores |
| `GN_CHROME_BINARY` | `/usr/bin/chromium` na imagem | Navegador do Selenium |
| `PORTA` | `5000` | Porta publicada |

### Arquivos alterados no produto

| Arquivo | Mudança |
|---|---|
| `app.py` | Registra a tela do ETL e inicia o agendador; o mapa passou a ser lido de `processo_im/4_Mapa_GN` |
| `Dockerfile` | Contexto na própria pasta; bibliotecas do IM, Chromium e variáveis do ETL |
| `docker-compose.yml` | Contexto `.`; volumes do ETL; `ETL_SENHA`; `shm_size` |
| `.dockerignore` (novo) | Lista do que não entra na imagem |
| `Iniciar_Calculadora_Docker.sh` | Build com contexto `.`; mostra o endereço da tela do ETL |
| `Iniciar_Calculadora.bat` / `.sh` | Instalam também as bibliotecas do IM (para a tela funcionar localmente) |
| `templates/erro.html` | Mensagem não cita mais o `Atualizar_Calculadora.bat` |
| `.gitignore` | Ignora `data/etl/` |
| `README.md` | Seção "ETL da base tarifária", estrutura e rotas |

### Ações necessárias no servidor

- **Remover agendamentos antigos**: se o servidor tiver um `crontab` rodando o
  `AtualizarDados.sh`, remova-o. Os dois juntos fariam execuções duplicadas.
- **Base em volume, não mais na pasta do servidor**: o compose montava `./data` só para leitura;
  agora a base fica no volume `tarifas`. Na primeira subida, ele recebe o `data/tarifas.json` da
  imagem. Se a base atual do servidor for mais nova que a do repositório, copie-a para dentro antes
  do primeiro ETL: `docker cp data/tarifas.json calculadora-gn:/app/data/tarifas.json`.
- **Acesso à internet**: o contêiner precisa sair para os sites das 17 distribuidoras. Quase todos
  os extratores **ignoram proxy** (`trust_env = False` no código do IM). Se o servidor só acessar a
  internet por proxy, esses extratores vão falhar e o código do IM precisará de ajuste (fora do
  escopo desta versão).
- **Atualizar uma instalação existente**: `docker compose down` e depois
  `./Iniciar_Calculadora_Docker.sh`. O `docker compose down -v` **apaga os volumes** (histórico,
  logs, base publicada); evite.
- **Sem Docker (systemd)**: o `deploy/calculadora-gn.service` não liga o agendador. Para usá-lo,
  acrescente `Environment=ETL_AGENDADOR=1` e instale o Chromium no servidor.

### Testes e arquivos que podem precisar de ajuste

- `tests/test_paridade_js.py` continua comparando com `5_Calculadora_Final/app.js` na raiz e é
  pulado quando não há Node.js. Não foi alterado.
- O `.dockerignore` da **raiz** do projeto não é mais usado pelo build; pode ser removido quando
  ninguém mais construir pela raiz.
- O `processo_im/1_Processo_Extracao_Dados/Comece_aqui/README.md` (do IM) ainda descreve o fluxo
  pelo `.bat`/`.sh`. Foi mantido como está, por ser documentação original; o `processo_im/LEIA-ME.md`
  explica o fluxo novo.

## Pontos de atenção

- **A primeira execução muda valores na calculadora.** A base atual é de 03/09/2026. No teste
  sem acessar os sites, 77 dos 459 registros saíram diferentes. É o comportamento do processo do IM
  (por exemplo, as tarifas de SP são arredondadas para 2 casas: 7,732893 → 7,73), e não foi alterado.
- **Cruzamento por pontuação do IM.** O `atualizar_calculadora.py` atualiza cada linha do
  `Tarifario_GN.xlsx` pela linha extraída "mais parecida" (pontuação ≥ 9). Pode trocar tarifas entre
  segmentos parecidos. Também foi mantido como está nesta versão.
- **Extratores frágeis** (herdados do IM): dependem de textos ou posições fixas nos sites
  (SCGás, Cigás, Gasmig, Potigás, RJ, Naturgy SP). Quando um site muda, o extrator falha. A
  execução fica `erro` e a calculadora continua com a base anterior; o log mostra qual UF falhou.
- **Duração.** Uma execução completa leva vários minutos (cada extrator tem limite de 15 minutos).
- **Reinício durante a execução** interrompe o ETL. Ele aparece como `interrompida` e não publica nada.
- **Docker não testado localmente.** O build, o Chromium e o agendamento dentro do contêiner
  precisam ser validados no servidor (seção "Como testar", item 3).
- **Tela sem senha** se `ETL_SENHA` não for definida: qualquer pessoa que conheça o endereço pode
  disparar o ETL ou mudar o agendamento.
