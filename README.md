# Calculadora GLP x GN — versão Python (Flask)

Mesma tela e mesmos resultados da `5_Calculadora_Final`, mas agora **filtros, cálculo,
formatação e montagem das tabelas rodam em Python**. O navegador só envia as
premissas escolhidas e mostra o HTML devolvido pelo servidor.

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
sudo dnf install -y python3.11 hostname
cd /opt/calculadora-gn/6_Calculadora_Flask
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

A atualização das tarifas no Linux é feita pelo
`1_Processo_Extracao_Dados/Comece_aqui/AtualizarDados.sh`, que já gera o `data/tarifas.json`.
Veja o `README.md` daquela pasta.

## Atualização das tarifas

Continua igual: rode o `5_Calculadora_Final\Atualizar_Calculadora.bat`. O
`3_Manutencao\atualizar_calculadora.py` agora grava **os dois arquivos**:

- `5_Calculadora_Final\tarifas.js`, usado pela versão estática;
- `6_Calculadora_Flask\data\tarifas.json`, usado por esta versão.

Não é preciso reiniciar o servidor, porque ele detecta que o arquivo mudou e recarrega.

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
data/tarifas.json          base tarifária
```

## Rotas

| Rota | Uso |
|---|---|
| `/` | Calculadora. Aceita `?uf=&segmento_copa=&concessionaria=&tipo_entrada=glp\|gn&volume=` e funciona até sem JavaScript |
| `/api/calcular` | Mesmos parâmetros. Devolve filtros, valores numéricos e o HTML dos resultados |
| `/api/tarifas` | Base tarifária carregada |
| `/saude` | Status e data de geração da base |
| `/mapa/` | Mapa de GN (servido direto da pasta `4_Mapa_GN`) |

## Diferença intencional em relação ao original

Quando não há tarifa para a combinação (ou o volume é inválido), o `app.js` deixava na
tela os cabeçalhos "PIS/Cofins (R$ | x%)" e o texto de faixas do cálculo anterior. Esta
versão volta aos textos padrão.
