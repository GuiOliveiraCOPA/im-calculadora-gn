# Plano — correção da extração de SP e MT

**Data:** 19/10/2026
**Escopo:** só a ingestão de SP e MT (`1_Processo_Extracao_Dados`)
**Origem:** execução `Execucoes_CMD/Execucao_002_2026-10-19_QAIP.log` (status 1: SP e MT com `erro ao executar`).
Itens D1 e D2 do `compilado_problema_dados.md`.

**Objetivo:** voltar o fluxo ao normal (status 0), extraindo as tarifas vigentes de SP e MT,
**sem mudar o formato** das planilhas `Sp_AAAA-MM-DD.xlsx` e `Mtgas_AAAA-MM-DD.xlsx`. Assim, o
`codigo_central.py`, a `Planilha_GN_Atualizada.xlsx` e o `tarifas.js` continuam recebendo os dados
no mesmo formato de hoje.

**Fora do escopo:** qualquer ajuste manual de valores, a base `2_Bases_Origem/Tarifario_GN.xlsx`, o
cruzamento do `3_Manutencao/atualizar_calculadora.py`, o `5_Calculadora_Final/tarifas.js` e o `4_Mapa_GN`.

---

## 1. Como o processo funciona (resumo)

```
17 sites ──tabela_*.py──> Fonte_Dados/PlanilhasUf/<Nome>_<data>.xlsx
                              │
                              └─codigo_central.py──> Planilha_Final/Planilha_GN_Atualizada.xlsx
                                                          │  (+ PassadoTarifas/ quando a tarifa muda)
2_Bases_Origem/Tarifario_GN.xlsx ──┐                      │
                                   └──3_Manutencao/atualizar_calculadora.py (Atualizar_Calculadora.bat)
                                                          │
                                                          └──> 5_Calculadora_Final/tarifas.js
```

- **Extração** (`AtualizarDados.bat` → `codigo_central.py`): roda cada `tabela_*.py` em subprocesso.
  Se um extrator falha, o central usa a **última planilha daquela UF** em `PlanilhasUf` e termina com status 1.
  Hoje SP está com a planilha de **03/09/2026** e MT com a de **15/09/2026**.
- **Tratamento** (`codigo_central.standardize_worksheet`): lê cada aba da planilha final e identifica
  cabeçalhos (faixa, tarifa, termo fixo). A aba SP usa números no padrão **US**, com tarifa no formato
  `R$ 7.73` e faixa no formato `2,000.010`; as outras UFs usam o padrão BR.
- **Base da calculadora** (`atualizar_calculadora.py`): para cada linha da base manual `Tarifario_GN.xlsx`,
  procura a linha extraída mais parecida (pontuação ≥ 9) e substitui **só a tarifa e o termo fixo**.
  Esta etapa não muda com o plano.

---

## 2. Diagnóstico

Reproduzido em 19/10/2026 com os sites no ar.

### 2.1 SP — `decimal.InvalidOperation`

**Causa raiz:** os PDFs novos da ARSESP (Diário Oficial de SP) trazem um **carimbo de assinatura
digital** em todas as páginas. Quando a quebra de página cai no meio de uma tabela, o texto do
carimbo é lido como se fosse parte da linha da tarifa:

```
1
0,00 a 1,00 m3
10,54
2,337387
Este documento pode ser verificado pelo codigo 2026.09.09.1.1.35.18.203.2113787
em https://www.doe.sp.gov.br/autenticidade
3/12
Documento assinado digitalmente conforme MP no 2.200-2/2001,
que institui a Infraestrutura de Chaves Publicas (ICP-Brasil).
```

O `parse_sp_segment_rows` pega os dois últimos números do bloco (`2001,` e `.`) como termo fixo e
tarifa. A faixa fica `0,00 a 1,00 m3 10,54 2,337387 em https://...`, e o `Decimal()` falha.

| Fonte | PDF atual | Situação |
|---|---|---|
| Comgás | Deliberação ARSESP 1.846 (09/09/2026, vigência 10/09/2026) | **Falha** em Residencial classe 1 (carimbo na página 3) |
| Naturgy SP | Deliberação ARSESP 1.840 (28/08/2026, vigência 31/08/2026), agora **com texto** | OK. O carimbo cai depois de "Notas:" |
| Necta | Deliberação ARSESP 1.847 (09/09/2026, vigência 10/09/2026) | **Falha** em Res. Medição Coletiva, classe "> 300" |

O seletor de URLs está correto: os três PDFs selecionados são os vigentes.

### 2.2 MT — `Nao foi possivel localizar o PDF tarifario vigente`

**Causa raiz:** a MTGás tirou da página o link do PDF `Tarifa-Vigente-MTGAS-01-2026.pdf` (o arquivo
ainda existe no servidor, mas está **desatualizado**). A tarifa vigente passou a ser publicada como
**tabela HTML na própria página**, com o título **"TARIFA VIGENTE A PARTIR DE 01/10/2026"**. Essa tabela
tem as mesmas 9 colunas e as mesmas 2 linhas de cabeçalho da tabela do PDF antigo.

- O "Publicação Reajuste 02-2026" é a ata do Diário Oficial (AGER/MT), em texto corrido, sem tabela.
- O link "Tabela Tarifa Vigente" aponta para um `tarifa_GN.xlsx` de **02/2025**. Está desatualizado e não deve ser usado.

### 2.3 Provas de conceito (executadas fora do projeto, sem alterar arquivos)

- **SP:** com as linhas do carimbo removidas antes do parser, a extração gera **56 linhas** (Comgás 19,
  Naturgy 21, Necta 16), no mesmo formato e com o mesmo total da planilha anterior. Os valores conferem com os PDFs.
- **MT:** a tabela HTML passada ao `build_relevant_blocks` atual gera os mesmos 3 blocos
  (Residencial, Comercial e Industrial, Industrial Fertilizantes), com as mesmas colunas da planilha de 15/09.

---

## 3. Correções

### Etapa 1 — `Fonte_Dados/tabela_sp.py`

1. **Remover o carimbo do DOE-SP antes de montar as linhas** (`clean_block_lines`, linha 208):
   descartar as linhas que contêm `Este documento pode ser verificado`, `doe.sp.gov.br/autenticidade`,
   `Documento assinado digitalmente`, `Infraestrutura de Chaves Publicas`, além das linhas que contêm só a
   paginação (`^\d+/\d+$`, ex.: `3/12`). Hoje a lista já descarta `"Este documento pode"`, mas
   não descarta as linhas seguintes do carimbo.
   - `3/12` não casa com `re.fullmatch(r"\d+", line)`, a regra que identifica a classe em
     `parse_sp_segment_rows`, então os dois filtros não conflitam.
2. **Mensagem de erro clara** em `build_output_row`: capturar a falha de conversão e relançar com
   concessionária, segmento e o texto da faixa. Assim, a próxima mudança de layout fica óbvia no log, sem
   precisar reproduzir o erro.
3. **Sem mudança de formato:** as colunas, o padrão US (`R$ 7.73`, `2,000.010`) e o nome `Sp_<data>.xlsx` continuam os mesmos.

### Etapa 2 — `Fonte_Dados/tabela_mtgas.py`

1. **Nova função `extract_html_table(html)`:** procura na página a `<table>` cujo cabeçalho tem
   `Segmento` e `Total s/ Imp` e devolve as linhas no mesmo formato `List[List[str]]` do
   `extract_pdf_table`. As 2 primeiras linhas são o cabeçalho, que o `build_relevant_blocks` já descarta.
2. **`main()` com a tabela HTML como fonte principal e o PDF como reserva:**
   - se encontrar a tabela HTML, usa `build_relevant_blocks(rows)` direto;
   - senão, segue o caminho atual (`find_latest_tariff_pdf_url` → PDF).
3. **Aba `controle`:** gravar a origem usada (URL da página ou do PDF) e o título de vigência lido da
   página (`TARIFA VIGENTE A PARTIR DE 01/10/2026`). As colunas de dados continuam iguais.
4. **Não usar** o `tarifa_GN.xlsx` nem o `Tarifa-Vigente-MTGAS-01-2026.pdf` como reserva, porque estão desatualizados.
5. A busca com Selenium continua igual. O `page_source` também contém a tabela.

### Etapa 3 — Rodar e validar a extração

1. Fechar a `Planilha_GN_Atualizada.xlsx`.
2. Rodar só as UFs corrigidas: `AtualizarDados.bat --only SP,MT`. Os argumentos são repassados ao `codigo_central.py`.
3. Conferir se `Sp_2026-10-19.xlsx` e `Mtgas_2026-10-19.xlsx` têm a mesma estrutura das planilhas anteriores
   (abas, colunas, títulos de bloco, número de linhas) e se os valores são os publicados nas fontes (seção 4).
4. Rodar o `AtualizarDados.bat` completo e conferir **Status: 0** no log e as abas SP e MT da planilha final.

---

## 4. Referência para conferir a extração

Valores publicados nas fontes em 19/10/2026, que as planilhas extraídas devem refletir. Nenhum valor é
digitado ou ajustado à mão: eles vêm da extração.

**SP:** 56 linhas. Em relação à planilha de 03/09, só mudam as tarifas de Industrial e Interruptível
da Comgás (ex.: faixa 0–50.000: 4,446748 → `R$ 4.45`) e da Necta (ex.: faixa 0–5.000: 3,973843 → `R$ 3.97`).

**MT:** 3 blocos, 9 linhas. Em relação à planilha de 15/09, só muda Comercial e Industrial – faixa 0–22.000:
IRPGT de `-0,3038` para `-0,1064`, total sem impostos de `2,9101` para `3,1075` e total com impostos de `3,2322` para `3,4514`.

---

## 5. Arquivos alterados por este plano

| Arquivo | Tipo de alteração |
|---|---|
| `1_Processo_Extracao_Dados/Comece_aqui/Fonte_Dados/tabela_sp.py` | Código (etapa 1) |
| `1_Processo_Extracao_Dados/Comece_aqui/Fonte_Dados/tabela_mtgas.py` | Código (etapa 2) |
| `PlanilhasUf/`, `Planilha_Final/`, `PassadoTarifas/`, `Execucoes_CMD/` | Gerados pela execução (etapa 3) |

Seguindo o padrão da pasta, antes de editar cada extrator salvar uma cópia
`tabela_<x>_backup_antes_<motivo>_<AAAAMMDD>.py` em `Fonte_Dados`.
