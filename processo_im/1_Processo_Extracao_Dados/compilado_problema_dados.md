# Compilado — problemas de dados e riscos da Calculadora GLP x GN

**Atualizado em:** 30/09/2026

**Fontes:**
- `problema_dados.md` (29/09/2026), itens citados como **PD1-n**;
- `problema_dados2.md`, seções 9 (riscos técnicos) e 10 (validação com o negócio), itens citados como **PD2-9.n** e **PD2-10.n**.

Os números citados (25 registros em cascata com termo fixo, 80 grupos sem mistura de cascata) foram
recalculados na base atual e conferem.

**Legenda de status**

| Status | Significado |
|---|---|
| **Resolvido** | Corrigido no código e testado |
| **Resolvido (implantar)** | Pronto no código; falta subir no servidor ou no Databricks |
| **Parcial** | Mitigado ou resolvido só em parte |
| **Aberto** | Problema técnico ainda sem correção |
| **Decisão** | Depende de resposta do negócio; o código mantém o comportamento atual |

## Decisão já tomada

> **Mantemos os dados antigos para as UFs que não foram atualizadas.**

Quando o site de uma UF falha, a última planilha que funcionou continua valendo. Isso vale nos três
ambientes: Windows (`.bat`), Linux (`.sh`) e Databricks.

No Databricks, cada tarifa ainda registra de onde veio (`origem_valor`: extração atual, extração
anterior ou só da base manual). Assim fica visível quais UFs estão com dado mantido.

---

## Placar

| Status | Qtde |
|---|---|
| Resolvido / Resolvido (implantar) | 3 (R1, R3, R4) |
| Parcial | 10 (R2, R5 a R10, D4, T1, T13) |
| Aberto (técnico) | 17 (D1 a D3, D5, T2 a T12, T14, T15) |
| Decisão (negócio) | 25 (N1 a N25) |

---

## 1. O que a migração para Python já resolveu

| # | Item | Status | Como foi resolvido | Origem |
|---|---|---|---|---|
| R1 | `pypdf` não declarado no `requirements.txt` | Resolvido | Incluído em `Fonte_Dados/requirements.txt` e nas dependências do pacote do Databricks. A instalação limpa no AlmaLinux funcionou | PD2-9.2 |
| R2 | Falta de teste automatizado | Parcial | Calculadora: 32 testes, incluindo comparação com o `app.js` original em 3.040 cenários e 1.995 combinações de filtros, sem diferença. Databricks: 20 testes mais uma execução completa em Spark local. **Os extratores continuam sem teste** | PD2-9.17 |
| R3 | Nenhum agendador nem alerta de execução | Resolvido (implantar) | Databricks: agendamento semanal (pausado até o 1º teste), e-mail em caso de falha, tabela `gn_silver.qualidade_execucao` e view `gn_gold.vw_saude_extracao`, que mostra há quantos dias cada UF está sem atualizar. Linux: `AtualizarDados.sh` pode ir para o cron, com log por execução | PD2-9.15 |
| R4 | Pasta `AmbientePython` ausente; dependência do Python de cada máquina | Resolvido | `AtualizarDados.sh` e `Iniciar_Calculadora.sh`/`.bat` criam o próprio ambiente (`.venv`) e instalam as dependências. O Databricks instala tudo pelo pacote | PD2-9.19 |
| R5 | Selenium no Linux e no Databricks (CE, PE, MS, MT) | Parcial | Os extratores passaram a usar Chrome/Chromium com as opções exigidas em servidor; no Linux, o Edge é ignorado. O Databricks tem init script que instala o Chrome. Testado no AlmaLinux: CE, PE e MS rodaram. **Falta:** fixar a versão do Chrome (hoje instala a mais recente) e o cluster ainda precisa de acesso à internet | PD2-9.3 |
| R6 | Calculadora parada com a base de 03/09 (etapa manual não rodada) | Parcial | No Linux, o `AtualizarDados.sh` faz extração e atualização da calculadora juntas. No Databricks, a tarefa `publicar` gera o `tarifas.json`. **Falta rodar uma atualização completa** e definir quem é responsável | PD1-3 |
| R7 | Divergência das constantes entre as duas cópias do `app.js` | Parcial | A calculadora Python tem **uma única fonte** das constantes (`calculadora/calculo.py`), com os valores da cópia ativa (0,826087 e 1,6377). **Falta:** apagar as cópias antigas da raiz (`app.js`, `index.html`, `tarifas.js`) e confirmar qual valor é o correto (item N1) | PD2-9.1 |
| R8 | Relatório de exceções do cruzamento extração × base manual | Parcial | No Databricks, cada tarifa traz `origem_valor`, e a regra de qualidade `tarifas_so_da_base_referencia` conta as linhas sem correspondência: **128 de 459 hoje**. O cruzamento em si continua por pontuação (item T13) | PD2-10.15 |
| R9 | Campos descartados (`Tabela`, `Período de renovação`, `Classe`, vigência e contrato da BA) | Parcial | Na bronze do Databricks, `tarifario_referencia` guarda a linha inteira da base manual, incluindo `Tabela` e `Período de renovação`. As planilhas originais de cada UF ficam arquivadas no Volume. `Classe` entrou na silver e no fato. **Falta decidir se esses campos devem aparecer na calculadora** (item N10) | PD2-10.10, 10.11, 10.12 |
| R10 | Periodicidade da extração | Parcial | Configurável: no Databricks vem semanal (segunda-feira, 6h); no Linux, via cron. **A cadência desejada é decisão do negócio** (item N17) | PD2-10.19 |

Também passou a existir, e não constava nos documentos:

- a calculadora **recusa uma base de tarifas inválida** (campo vazio, faixa invertida, alíquota fora de 0–100%) e mostra uma página de erro em vez de calcular errado;
- a silver do Databricks tem **regras CHECK** que impedem gravar tarifa negativa ou faixa invertida;
- uma regra de qualidade avisa **reajustes acima de 30%** entre execuções.

---

## 2. Situação dos dados hoje

| # | Item | Prioridade | Status | Detalhe | Origem |
|---|---|---|---|---|---|
| D1 | Extrator de **SP** parou de funcionar | Alta | Aberto | `tabela_sp.py` falha com `decimal.InvalidOperation`: o PDF mudou de formato. Falha igual no Windows e no Linux. Comgás, Naturgy SP e Necta seguem com os dados de 03/09. Em 15/09 já tinha falhado por erro 504 da Naturgy | PD1-1 |
| D2 | **MT** publicou reajuste que não está na calculadora | Alta | Aberto | O site não tem mais o PDF de "tarifa vigente"; publica "Publicação Reajuste 02-2026" (set/2026). O extrator não encontra o arquivo, e a calculadora provavelmente mostra a tarifa anterior ao reajuste | PD1-2 |
| D3 | Tarifas perdem casas decimais na extração | Média | Aberto | Alguns extratores gravam 2 casas, contra até 6 na base manual. Ex.: Comgás Residencial Coletivo **7,732893 → 7,73 R$/m³** (~0,04%). Pode gerar divergência com o BI | PD1-5 |
| D4 | `dt_delib` é manual e tem erro no CE | Média | Parcial | A data não é atualizada junto com a tarifa. 6 linhas do CE têm `001/07/2026`. O Databricks já sinaliza as datas inválidas (regra `data_deliberacao_invalida` = 6); **a correção na base é manual** | PD1-7 |
| D5 | Inconsistências na aba `Calculo impostos` | Baixa | Aberto | Valor `2.617433` repetido em 2 linhas que deveriam diferir e 2 células `#REF!`. Ver também N9 | PD2-9.12 |

---

## 3. Pendências técnicas nos extratores e no processo

Nenhum destes itens foi alterado na migração: os extratores foram reaproveitados como estão, para
não mudar o resultado atual.

| # | Item | Prioridade | Status | Detalhe | Origem |
|---|---|---|---|---|---|
| T1 | SP e RJ sem tratamento de erro nem nova tentativa | Alta | Parcial | Dependem da Naturgy, que já deu erro 504. No Databricks, a tarefa de extração tenta **1 vez de novo após 10 min**, e a UF mantém o dado anterior se falhar. **Falta nova tentativa dentro do próprio extrator** | PD2-9.4 |
| T2 | RJ separa segmentos pela **posição das linhas** no PDF | Alta | Aberto | `tabela_rj.py:326-330`. Se um bloco anterior mudar de tamanho, a tarifa vai para o segmento errado **sem erro**. Termo fixo fixo em `"0,00"` em 100% das linhas do RJ (linha 334). ~170 linhas de código morto copiadas do SP | PD1-8, PD2-9.5 |
| T3 | SCGás procura o PDF pelo texto fixo **"DOESC 31/12/2025"** | Alta | Aberto | Não pega a próxima publicação. Além disso, descarta 3 de 6 segmentos mapeados (Industrial TG2, TG3, Matéria Prima; linhas 109-143). Ver N16 | PD1-8, PD2-9.6 |
| T4 | Cigás usa **links fixos de PDF** como reserva | Média | Aberto | `tabela_cigas.py:62-65`. Se o site republicar, pode usar PDF antigo sem avisar | PD1-8, PD2-9.7 |
| T5 | Naturgy SP usa **tabela digitada** da Deliberação 1806/2026 | Média | Aberto | Usada quando o PDF vem como imagem. Pode manter valores antigos | PD1-8 |
| T6 | Gasmig (MG) e Potigás (RN) leem tabelas **pela posição** na página | Média | Aberto | Se o site mudar a ordem, os dados saem trocados sem erro | PD1-8 |
| T7 | Sergipe Gás (SE) publica o Industrial **por semana**, sem conversão para mês | Média | Aberto | `tabela_sergipegas.py:113-114`. A PB também tem nota de dado semanal (×4,345) | PD1-9, PD2-9.8 |
| T8 | Nenhuma conversão automática de tarifa **semanal** | Média | Aberto | Só dia→mês é tratado (`codigo_central.py:380-411`). Risco de erro de ~4,3× se outro fornecedor publicar por semana. Ver N14 | PD2-9.10 |
| T9 | Copergás (PE): cabeçalho em duas linhas | Média | Aberto | O leitor genérico (`codigo_central.py:1028-1053`) assume uma linha só. Risco de misturar colunas "com/sem tributos". Ver N13 | PD2-9.9 |
| T10 | MSGás (MS): filtros de texto com acentuação corrompida | Média | Aberto | Linhas de outras matérias do Diário Oficial podem entrar no Anexo IX. **Não confirmado** com dados publicados | PD1-9 |
| T11 | Sulgás (RS): conversão dia→mês remove as vírgulas | Média | Aberto | Só fica correta para faixas inteiras. **Não confirmado** com dados publicados | PD1-9 |
| T12 | Cegás (CE): tabela sem cabeçalho e sem registro de fonte | Baixa | Aberto | Dificulta a conferência; é o extrator mais frágil (depende só do navegador) | PD1-9, PD2-9.3 |
| T13 | Cruzamento extração × base manual **por pontuação**, sem chave estável | Média | Parcial | `atualizar_calculadora.py:130-159` (limiar ≥ 9). Uma tarifa pode deixar de ser atualizada sem aviso. Agora isso **fica visível** no Databricks (R8), mas o método é o mesmo | PD2-9.13 |
| T14 | Regra de impostos embutidos lida de **texto livre** (`preco_concessionaria`) | Média | Aberto | A mesma regra foi levada ao Python e ao Databricks. Hoje só existem 3 rótulos, e todos são reconhecidos. Um rótulo novo seria interpretado errado sem erro. Ver N7 | PD2-9.11 |
| T15 | README do mapa aponta para script que só existe na pasta antiga | Baixa | Aberto | `3_Manutencao/README_mapa.md:22` → `manutencao/power-automate/OfficeScript-exportar-municipios.ts`. Mover antes de apagar `manutencao/`. Ver N18 | PD2-9.14 |

---

## 4. Decisões com o negócio

### Cálculo e tributos

| # | Pergunta | Prioridade | Situação atual no código | Origem |
|---|---|---|---|---|
| N1 | Imposto monofásico do GLP: **R$ 1,6377/kg** ou **R$ 1,47/kg**? Qual a fonte e a data de vigência? Quem avisa quando mudar? | Alta | Usa 1,6377 (cópia ativa). Nenhum documento explica esse valor; 1,47 aparece na aba `conversa_com_o_tributario`. Afeta **todas** as simulações | PD1-4, PD2-10.1 |
| N2 | Fator GN→GLP: **0,826087** ou **0,8264**? Qual a referência técnica do poder calorífico (1,210526)? | Alta | Usa 0,826087, que bate com o texto da tela | PD1-10, PD2-10.2 |
| N3 | Termo fixo em tarifas **em cascata**: cobrar ou não? | Alta | Não cobra, como diz o User Guide. As `notas_do_projeto.md` dizem o contrário. **Impacto confirmado:** 25 registros (19 Compagás/PR, 6 Bahiagás/BA) com termo fixo entre **R$ 6,81 e R$ 159,25** hoje ignorado | PD1-10, PD2-9.16, PD2-10.4 |
| N4 | Crédito de impostos: continuar decidindo só pelo segmento "INDUSTRIAL" ou perguntar o **regime tributário** do cliente (Lucro Real credita; Simples não)? | Alta | Só o segmento INDUSTRIAL vê o comparativo com crédito | PD2-10.3 |
| N5 | Regra de impostos "por dentro" (PIS/Cofins, depois ICMS) nunca foi validada formalmente | Média | Mantida; o próprio autor anotou que "deve ser validada com a área" | PD2-10.5 |
| N6 | Fim do PIS/Cofins em 01/01/2027 e redução do ICMS a partir de 2029 | Média | Não tratado. Planejar quando e como atualizar | PD1-10 |
| N7 | Trocar o texto `preco_concessionaria` por campos sim/não explícitos (`inclui_pis_cofins`, `inclui_icms`) na base manual? | Média | O gold do Databricks já tem esses dois campos, mas **derivados do texto**. Resolve T14 | PD2-10.7 |
| N8 | Comparativo usa custo de GN reprojetado; **não há preço de GLP de mercado** na base. É intencional? | Média | Mantido | PD2-9.18, PD2-10.6 |

### Base manual e extração

| # | Pergunta | Prioridade | Situação atual no código | Origem |
|---|---|---|---|---|
| N9 | A aba `Calculo impostos` ainda é usada ou é rascunho? | Baixa | Não é lida por nenhum código | PD2-10.9 |
| N10 | `Tabela`, `Período de renovação`, vigência/contrato (BA) e `Classe` precisam aparecer no produto? | Baixa | Preservados na bronze do Databricks; `Classe` já está no fato (R9) | PD2-10.10, 10.11, 10.12 |
| N11 | Validar que **cascata** é igual dentro de cada grupo UF + concessionária + segmento? | Baixa | Hoje 0 de 80 grupos mistura (conferido). Pode virar uma regra de qualidade no Databricks | PD2-10.8 |
| N12 | Manter `dt_delib` manual ou atualizar junto com a tarifa? | Média | Manual (D4) | PD1-7 |
| N13 | PE (Copergás): adaptar o leitor genérico ou manter tratamento dedicado? | Média | Ver T9 | PD2-10.13 |
| N14 | Algum fornecedor ativo publica por **semana**? Automatizar a conversão (×4,345)? | Média | SE confirmado no código; PB tem nota. Ver T7/T8 | PD2-10.14 |
| N15 | O negócio sabe que tarifas podem ficar desatualizadas quando o cruzamento falha (128 linhas hoje)? | Média | Agora é visível no Databricks (R8). Ver T13 | PD2-10.15 |
| N16 | SCGás: extrair também Industrial TG2, TG3 e Matéria Prima? | Média | Não extraídos (T3) | PD2-10.16 |
| N17 | Cadência da atualização: diária, semanal ou sob demanda? | Média | Semanal no Databricks, pausado até confirmar (R10) | PD2-10.19 |
| N18 | Mover o script do Power Automate para a estrutura ativa | Baixa | Ver T15 | PD2-10.18 |

### Mapa, legado e implantação

| # | Pergunta | Prioridade | Situação atual no código | Origem |
|---|---|---|---|---|
| N19 | **Mapa:** quem mantém `Municipios_GN_tabular.xlsx` (fora do projeto; arquivo atual de 26/03/2026) e de onde vêm os status? | Média | O mapa roda igual, servido pela calculadora Python. O processo documentado não gera o arquivo atual | PD1-6, PD2-10.22 |
| N20 | **Mapa:** municípios atendidos no **PA (15), AP (3), MA (3) e DF (1)**, UFs "sem GN" na base. Estão certos? Se sim, faltam tarifas de Gás do Pará, Gasap, Gasmar e Cebgás | Média | Sem tarifa na calculadora | PD1-6 |
| N21 | Mapa entra no mesmo cronograma da calculadora? | Baixa | Nada | PD2-10.22 |
| N22 | Autorizar a exclusão do legado: `manutencao/`, `mapa-gn/`, `Pop Up/` e `app.js`/`index.html`/`tarifas.js` da raiz | Média | Ainda existem. A raiz tem as **constantes antigas** e abre direto no navegador (R7) | PD2-9.1, PD2-10.17 |
| N23 | Público de acesso (grupo do Entra ID) | Média | A calculadora Python não tem login hoje | PD2-10.20 |
| N24 | Padrão de hospedagem (política de TI: Azure Web App × Databricks Apps × servidor AlmaLinux) | Média | Pronta para AlmaLinux (serviço systemd). Não foi adaptada para Azure Web App nem Databricks Apps | PD2-10.21 |
| N25 | Sessão formal de validação (Sprint 0) com a área de IM, com exemplos numéricos e comparação com o Power BI "Comparativo GLP e GN - Empresarial" | Alta | A comparação com o `app.js` original já está automatizada; **falta a comparação com o Power BI** | PD2-10.23 |

---

## 5. Próximos passos sugeridos

1. **Tributário:** responder N1, N4, N5 e N6. N1 afeta todas as simulações.
2. **Manutenção:** corrigir os extratores de SP e MT (D1, D2) e, em seguida, rodar a atualização completa para levar as tarifas atuais à calculadora (R6).
3. **Inteligência de Mercado:** decidir N3 (termo fixo em cascata, com impacto de até R$ 159,25 por fatura) e N2.
4. **Manutenção:** priorizar os extratores que erram **sem avisar**: T2 (RJ), T3 (SC), T6 (MG/RN), T7 (SE).
5. **Conferência manual:** comparar MS, RS, SE e CE com os sites oficiais (T7, T10, T11, T12).
6. **Governança:** autorizar a exclusão do legado (N22) e definir acesso e hospedagem (N23, N24).
7. **Sprint 0** (N25), usando o compilado como pauta.

---

## Anexo — de onde veio cada item

| Documento original | Item | Neste compilado |
|---|---|---|
| problema_dados.md | 1 SP parou | D1 |
| | 2 MT reajuste | D2 |
| | 3 Calculadora com base de 03/09 | R6 |
| | 4 GLP R$ 1,6377 sem fonte | N1 |
| | 5 Casas decimais | D3 |
| | 6 Mapa | N19, N20 |
| | 7 `dt_delib` | D4, N12 |
| | 8 Textos e posições fixos | T2, T3, T4, T5, T6 |
| | 9 Erros de leitura (MS, RS, SE, CE) | T10, T11, T7, T12 |
| | 10 Premissas (fator, cascata, PIS/Cofins 2027) | N2, N3, N6 |
| problema_dados2.md §9 | 9.1 Constantes divergentes | R7, N22 |
| | 9.2 pypdf | R1 |
| | 9.3 Selenium | R5, T12 |
| | 9.4 SP/RJ sem tratamento de erro | T1 |
| | 9.5 RJ posição fixa | T2 |
| | 9.6 SCGás | T3 |
| | 9.7 Cigás URLs fixas | T4 |
| | 9.8 SE semanal | T7 |
| | 9.9 PE cabeçalho duplo | T9 |
| | 9.10 Sem conversão semanal | T8 |
| | 9.11 Texto `preco_concessionaria` | T14 |
| | 9.12 Aba `Calculo impostos` | D5 |
| | 9.13 Cruzamento por pontuação | T13 |
| | 9.14 README do mapa | T15 |
| | 9.15 Sem agendador/alerta | R3 |
| | 9.16 Termo fixo em cascata | N3 |
| | 9.17 Sem testes | R2 |
| | 9.18 Sem preço de GLP real | N8 |
| | 9.19 AmbientePython ausente | R4 |
| problema_dados2.md §10 | 10.1, 10.2 | N1, N2 |
| | 10.3 a 10.9 | N4, N3, N5, N8, N7, N11, N9 |
| | 10.10, 10.11, 10.12 | N10 (e R9) |
| | 10.13, 10.14, 10.15, 10.16 | N13, N14, N15, N16 |
| | 10.17, 10.18, 10.19 | N22, N18, N17 |
| | 10.20, 10.21, 10.22, 10.23 | N23, N24, N21, N25 |
