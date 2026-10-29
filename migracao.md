# Migração da Calculadora GLP x GN para Python (Flask)

> **Documento histórico.** Descreve a migração como foi feita no repositório `IA - Calculadora GN`
> (Azure DevOps). Lá esta calculadora ficava na pasta `6_Calculadora_Flask`, que hoje é a raiz deste
> repositório: onde o texto diz `6_Calculadora_Flask/`, leia a raiz. Pastas citadas como
> `5_Calculadora_Final`, `1_Processo_Extracao_Dados` etc. na raiz do projeto não fazem parte deste
> repositório (as usadas pela calculadora estão em `processo_im/`). Estado atual: [README.md](README.md).

**Data:** 29/09/2026
**Versão anterior:** `5_Calculadora_Final` (HTML + JavaScript no navegador)
**Versão nova:** `6_Calculadora_Flask` (servidor Python com Flask)

## Resumo

A calculadora foi convertida para Python/Flask. Filtros, cálculo, formatação e montagem
das tabelas agora rodam no servidor Python. O navegador só envia as premissas escolhidas
e exibe o resultado devolvido pelo servidor.

A tela ficou visualmente idêntica, e os resultados também. Isso foi comprovado
automaticamente comparando a versão nova com o `app.js` original em **3.040 cenários de
cálculo** e **1.995 combinações de filtros**, sem nenhuma diferença.

A versão `5_Calculadora_Final` não foi alterada e continua funcionando.

## Como executar

Dê dois cliques em **`6_Calculadora_Flask\Iniciar_Calculadora.bat`**.

1. Na primeira vez, ele prepara o ambiente Python (`.venv`) e instala o necessário.
2. Depois sobe o servidor e abre o navegador em http://127.0.0.1:5000.
3. Para encerrar, feche a janela preta (ou use Ctrl+C).

Requisito: Python 3 instalado na máquina.

## O que passou a rodar em Python

| Responsabilidade | Arquivo |
|---|---|
| Cálculo com e sem cascata, impostos, conversão GLP↔GN | `calculadora/calculo.py` |
| Filtros de estado → segmento → concessionária | `calculadora/filtros.py` |
| Números e valores em reais no padrão brasileiro | `calculadora/formatacao.py` |
| Leitura e validação das tarifas | `calculadora/dados.py` |
| Montagem das tabelas e resultados | `templates/_resultados.html` |
| Rotas do servidor | `app.py` |

No navegador sobraram só dois scripts pequenos:

- `static/js/calculadora.js`: envia as escolhas da tela e mostra o que o Python devolve,
  sem nenhuma regra de cálculo;
- `static/js/premissas.js`: abre e fecha o balão de premissas.

A página também funciona com o JavaScript desligado, com um botão "Calcular".

## Atualização das tarifas

O processo continua o mesmo: rodar o `5_Calculadora_Final\Atualizar_Calculadora.bat`.

O script `3_Manutencao\atualizar_calculadora.py` foi ajustado e agora grava **dois arquivos**:

- `5_Calculadora_Final\tarifas.js`, usado pela versão antiga;
- `6_Calculadora_Flask\data\tarifas.json`, usado pela versão nova.

Não é preciso reiniciar o servidor, porque ele percebe o arquivo novo e passa a usá-lo sozinho.

## Como os dados ficam protegidos

- **Tarifas com problema bloqueiam a tela.** Se a base vier com campo vazio, texto no
  lugar de número, alíquota fora de 0–100% ou faixa invertida, a calculadora mostra uma
  página de erro com a lista de problemas. Assim ela nunca calcula com dados errados.
- **Gravação segura do arquivo.** O `tarifas.json` é gravado primeiro num arquivo
  temporário e só depois substitui o anterior. Com isso, o servidor nunca lê um arquivo
  pela metade.
- **Textos da planilha são tratados com segurança.** Qualquer texto vindo da base é
  exibido como texto e não é interpretado como código na página.

## Como a equivalência foi verificada

1. **Teste de comparação com o original** (`tests/test_paridade_js.py`). Executa o
   `app.js` original e compara, texto a texto, com o que o Python gera. Cobre todas as
   combinações da base × 19 volumes diferentes × entrada em GLP e em GN.
   - Para confirmar que o teste realmente detecta erros, mudei uma constante do imposto
     do GLP na quarta casa decimal (1,6377 → 1,6378), e o teste falhou como esperado.
   - Requer o Node.js instalado; sem ele, o teste é pulado.
2. **Testes unitários** (`tests/test_app.py`) para regras de imposto, cascata, conversão,
   formatação, validação da base e rotas do servidor.
3. **Teste no navegador (Edge).** A mesma sequência de ações foi feita nas duas versões
   (trocar estado, segmento, concessionária, tipo de entrada e volume, e apagar e
   redigitar o volume). As telas ficaram iguais em todos os passos, e a ida e volta pelo
   Mapa de GN funciona.

Para rodar os testes:

```bat
cd 6_Calculadora_Flask
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Resultado atual: **32 testes aprovados**.

## Diferença intencional em relação ao original

Quando não existe tarifa para a combinação escolhida (ou o volume é inválido), a versão
antiga deixava na tela os percentuais de PIS/Cofins e ICMS e o texto de faixas do cálculo
anterior. A versão nova volta aos textos padrão.

## Pontos de atenção

- **Mudança de regra de cálculo.** Se no futuro uma regra mudar de propósito, o teste de
  comparação vai acusar diferença em relação ao `app.js` antigo. Nesse caso, ele deve ser
  ajustado ou desativado, e a versão Python passa a ser a referência.
- **Valores a conferir na base.** Três registros chamaram atenção. Foram mantidos como
  estão porque vêm da planilha:
  - SP / Comgás / Residencial, faixa 7,01–14: termo fixo **−4,63**;
  - SP / Comgás / Residencial, faixa acima de 14,01: termo fixo **−25,43**;
  - RS / Sulgás / Residencial Faturamento Individualizado, faixa 0–1: tarifa **0**.
- **Acesso por outras pessoas.** Por padrão, o servidor abre só no computador onde está
  rodando. Para colegas acessarem pela rede interna, defina `HOST=0.0.0.0` antes de
  iniciar (detalhes no `README.md`).

## Endereços disponíveis no servidor

| Endereço | Para que serve |
|---|---|
| `/` | Calculadora |
| `/api/calcular` | Mesmo cálculo da tela, em formato de dados (para integrações) |
| `/api/tarifas` | Base tarifária carregada |
| `/saude` | Confirma se o servidor está no ar e mostra a data da base |
| `/mapa/` | Mapa de GN (lido direto da pasta `4_Mapa_GN`) |

## Próximos passos sugeridos

- Atualizar o "User Guide - Calculadora de GN.txt" com a nova forma de execução.
- Conferir com a área responsável os três registros listados em "Pontos de atenção".
- Decidir se a versão `5_Calculadora_Final` continua em uso ou será aposentada.
