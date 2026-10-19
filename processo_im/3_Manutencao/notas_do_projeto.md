# Calculadora Web GLP x GN - Notas de Aprendizado

## Objetivo

Criar uma calculadora web baseada nas calculadoras do Power BI "Comparativo GLP e GN - Empresarial - versao 052026", usando a base `Tarifario_GN.xlsx`.

Nesta primeira versao, o foco e calcular a fatura de GN:

- sem cascata;
- com cascata;
- sem tributos;
- com PIS/Cofins;
- com PIS/Cofins + ICMS.

Depois podemos evoluir para comparacao completa GLP x GN.

## Base De Dados

Arquivo usado:

`C:\Users\7zz7\OneDrive - Copa Energia\IM - Documentos\General\GN\Bases_Painel_BI\Tarifario_GN.xlsx`

Aba usada:

`Tarifario`

Campos importantes:

- `UF`
- `Concessionária`
- `Segmento Copa`
- `Segmento`
- `Faixa Mín (m3)`
- `Faixa Máx (m3)`
- `Tarifa (R$/m³)`
- `Termo Fixo (R$)`
- `PIS/Cofins`
- `ICMS`
- `Tarifa em cascata?`

## Regra Sem Cascata

Na tarifa sem cascata, o consumo cai em uma unica faixa.

Exemplo:

```text
Consumo: 800 m3
Faixa encontrada: 501 a 1.000 m3
Tarifa: R$ X/m3
Termo fixo: R$ Y

Fatura liquida = (800 * X) + Y
```

Ou seja, a tarifa da faixa encontrada e aplicada ao consumo inteiro.

## Regra Com Cascata

Na tarifa com cascata, o consumo e quebrado faixa por faixa.

Exemplo:

```text
Faixa 1: 0 a 500 m3, tarifa A
Faixa 2: 500 a 1.000 m3, tarifa B

Consumo: 800 m3

500 m3 pagam tarifa A
300 m3 pagam tarifa B
```

O termo fixo, quando existir, e somado apenas da ultima faixa atingida.

```text
Fatura liquida = soma(consumo de cada faixa * tarifa da faixa) + termo fixo da ultima faixa
```

## Conversao GN Para GLP

Segundo a anotacao:

```text
Volume GLP = Volume GN * 0,826
```

Nesta versao, mostramos o volume equivalente em GLP como referencia.

## Tributos

A calculadora mostra tres cenarios:

1. Sem tributos
2. Com PIS/Cofins
3. Com PIS/Cofins + ICMS

Pela aba `Calculo impostos`, a premissa inicial e calcular imposto "por dentro":

```text
Com PIS/Cofins = Fatura liquida / (1 - PIS/Cofins)
Com PIS/Cofins + ICMS = Fatura liquida / (1 - PIS/Cofins) / (1 - ICMS)
```

Essa regra ainda deve ser validada com a area.

## Custo Unitario

```text
Custo unitario liquido = Fatura liquida / Volume GN
Custo unitario bruto = Fatura bruta / Volume GN
```

## Arquivos Do Projeto

- `extrair_tarifas.py`: le o Excel e gera `tarifas.js`.
- `tarifas.js`: base de tarifas em formato JavaScript.
- `index.html`: tela da calculadora.
- `styles.css`: visual da calculadora.
- `app.js`: regras, filtros e calculos.

