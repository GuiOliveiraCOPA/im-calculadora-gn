# Pontos de dados da Calculadora GLP x GN — para discussão

**Data do levantamento:** 29/09/2026
**Origem:** revisão dos códigos e planilhas do projeto, mais um teste completo de atualização
em servidor Linux (AlmaLinux 9) contra os sites reais das distribuidoras.

## Decisão atual

> **Por enquanto, mantemos os dados antigos para as UFs que não foram atualizadas.**

É isso que o processo já faz: quando o extrator de uma UF falha, a planilha final usa a
última planilha daquela UF que funcionou. Nenhum dado é apagado nem zerado. As UFs afetadas
hoje são **SP** e **MT** (itens 1 e 2).

---

## Resumo

| # | Ponto | Prioridade | Quem precisa responder |
|---|---|---|---|
| 1 | Extrator de SP parou de funcionar | Alta | Manutenção da automação |
| 2 | MT publicou reajuste que não está na calculadora | Alta | Inteligência de Mercado + manutenção |
| 3 | Calculadora está com tarifas de 03/09 | Alta | Quem roda a atualização |
| 4 | Imposto do GLP (R$ 1,6377/kg) sem fonte registrada | Alta | Tributário |
| 5 | Tarifas perdem casas decimais na extração | Média | Inteligência de Mercado |
| 6 | Mapa: fonte não documentada e divergência com a base | Média | Dono do mapa |
| 7 | Data da deliberação (`dt_delib`) é manual e tem erro no CE | Média | Inteligência de Mercado |
| 8 | Textos e posições fixos no código que vencem com o tempo | Média | Manutenção da automação |
| 9 | Possíveis erros de leitura em 4 extratores | Média | Manutenção da automação |
| 10 | Premissas do cálculo sem referência formal | Baixa | Inteligência de Mercado |

---

## 1. Extrator de SP parou de funcionar — Alta

- **O que acontece:** o `tabela_sp.py` falha com um erro ao ler uma faixa de consumo
  (`decimal.InvalidOperation`). Falha igual no Windows e no Linux: o PDF publicado mudou de formato.
- **Impacto:** Comgás, Naturgy SP e Necta ficam com os dados da última extração que funcionou
  (03/09/2026). Na extração de 15/09 o SP já tinha falhado (erro 504 no site da Naturgy).
- **Para discutir:**
  - Houve deliberação nova da ARSESP depois de 03/09?
  - Quem corrige o extrator e em que prazo?

## 2. MT publicou reajuste que não está na calculadora — Alta

- **O que acontece:** o site da MTGás não tem mais um PDF de "tarifa vigente", que é o que
  o extrator procura. Hoje ele publica **"Publicação Reajuste 02-2026"**, de setembro/2026.
- **Impacto:** a calculadora provavelmente mostra a tarifa de MT **anterior ao reajuste**.
- **Para discutir:**
  - Confirmar os valores do reajuste 02-2026 e a data de vigência.
  - Enquanto o extrator não é ajustado, vale atualizar MT à mão no `Tarifario_GN.xlsx`?

## 3. Calculadora está com tarifas de 03/09 — Alta

- **O que acontece:** a última extração foi em 15/09/2026, mas a etapa que leva as tarifas
  para a calculadora (`Atualizar_Calculadora.bat`) não foi rodada depois. A calculadora usa a base de 03/09/2026.
- **Impacto:** as UFs que atualizaram corretamente em 15/09 ainda não aparecem na calculadora.
- **Para discutir:**
  - Definir quem roda a atualização e com que frequência.
  - No servidor Linux, o `AtualizarDados.sh` faz as duas etapas juntas e pode ser agendado.

## 4. Imposto do GLP (R$ 1,6377/kg) sem fonte registrada — Alta

- **O que acontece:** a calculadora soma **R$ 1,6377 por kg** de GLP como alíquota monofásica.
  Esse valor não tem fonte registrada em nenhum arquivo do projeto.
- **Histórico:** a versão anterior usava **R$ 1,47/kg**, valor que aparece na aba
  `conversa_com_o_tributario` do `Tarifario_GN.xlsx` ("indústria pode creditar 1,47 a cada kg de GLP").
- **Impacto:** afeta diretamente a tarifa bruta e a fatura bruta do GLP em **todas** as simulações.
- **Para discutir:**
  - Qual a fonte do valor 1,6377 (norma, data de vigência)?
  - Quem avisa quando ele muda?
  - Registrar a resposta na aba do Tributário.

## 5. Tarifas perdem casas decimais na extração — Média

- **O que acontece:** alguns extratores gravam a tarifa com **2 casas decimais**, enquanto a
  base de referência tem até 6. No teste, a Comgás Residencial Coletivo passou de
  **7,732893 para 7,73 R$/m³**.
- **Impacto:** diferença pequena por m³ (cerca de 0,04% nesse exemplo), mas que se acumula em
  volumes grandes e pode gerar divergência com o BI. O User Guide já alerta para isso.
- **Para discutir:** a calculadora precisa bater exatamente com o BI? Se sim, os extratores
  devem guardar a precisão original do PDF.

## 6. Mapa: fonte não documentada e divergência com a base — Média

- **O que acontece:**
  - Os status dos municípios (atendido, em expansão, não atendido) vêm da planilha interna
    `Municipios_GN_tabular.xlsx`, que **não está no projeto**. O arquivo atual é de 26/03/2026.
  - O processo descrito em `3_Manutencao/README_mapa.md` não gera o arquivo atual.
  - O mapa mostra municípios atendidos no **PA (15), AP (3), MA (3) e DF (1)**, mas esses estados
    estão na lista de "UF sem GN" da base tarifária.
- **Para discutir:**
  - Quem mantém a planilha do mapa e de onde vêm os status?
  - Os municípios do PA, AP, MA e DF estão certos? Se sim, falta tarifa dessas distribuidoras
    na calculadora (Gás do Pará, Gasap, Gasmar, Cebgás).

## 7. Data da deliberação (`dt_delib`) é manual e tem erro no CE — Média

- **O que acontece:** a automação atualiza só a tarifa e o termo fixo. A data da deliberação
  continua a da base manual, mesmo quando a tarifa muda.
- **Erro encontrado:** 6 linhas do CE (Comerciais e de Serviços) têm a data digitada como `001/07/2026`.
- **Para discutir:** atualizar a data junto com a tarifa ou mantê-la manual com revisão periódica?

## 8. Textos e posições fixos no código que vencem com o tempo — Média

Estes extratores dependem de algo escrito no código que muda a cada publicação:

| UF | O que está fixo | Risco |
|---|---|---|
| SC | Procura o PDF pelo texto "DOESC 31/12/2025" | Não pega a próxima publicação |
| AM | Dois PDFs de reserva com link fixo | Pode usar PDF antigo sem avisar |
| SP (Naturgy) | Tabela digitada da Deliberação 1806/2026, usada se o PDF vier como imagem | Pode usar valores antigos |
| MG, RN | Tabelas lidas pela posição na página | Se o site mudar a ordem, os dados saem trocados sem erro |
| RJ | Segmentos separados pela posição das linhas no PDF | Idem |

**Para discutir:** criar uma checagem mensal desses pontos ou priorizar a correção?

## 9. Possíveis erros de leitura em 4 extratores — Média

Encontrados na revisão do código. Valem também no Windows; **ainda não foram confirmados
com os dados publicados**.

- **MSGás (MS):** textos de filtro com acentuação corrompida. Linhas de outras matérias do
  Diário Oficial podem entrar na tabela industrial (Anexo IX).
- **Sulgás (RS):** a conversão de faixas diárias para mensais remove as vírgulas. Só está
  certa para faixas com números inteiros.
- **Sergipe Gás (SE):** a faixa industrial é publicada **por semana** e não é convertida para mês.
- **Cegás (CE):** salva as tabelas sem cabeçalho e sem registro de fonte, o que dificulta a conferência.

**Para discutir:** conferir as tarifas dessas 4 UFs na calculadora contra o site oficial.

## 10. Premissas do cálculo sem referência formal — Baixa

- **Fator de conversão** 1 kg GLP = 1,210526 m³ GN (e 1 m³ GN = 0,826087 kg GLP):
  aparece nas premissas da tela, sem referência técnica citada.
- **Termo fixo na cascata:** a calculadora não cobra termo fixo quando a tarifa é em cascata,
  mas as notas do projeto (`notas_do_projeto.md`) falam em somar o termo fixo da última faixa.
  Confirmar a regra correta.
- **Fim do PIS/Cofins em 01/01/2027 e redução do ICMS a partir de 2029** (aba do Tributário):
  a calculadora ainda não trata essas mudanças. Precisamos planejar quando atualizar.

---

## Próximos passos sugeridos

1. Responsáveis por cada item da tabela de resumo.
2. Tributário: confirmar o valor e a fonte do imposto do GLP (item 4).
3. Manutenção: corrigir os extratores de SP e MT (itens 1 e 2).
4. Rodar a atualização completa e levar as tarifas atuais para a calculadora (item 3).
5. Conferir MS, RS, SE e CE contra os sites oficiais (item 9).
