# Mapa de disponibilidade de GN — versão publicável

Página web estática para consulta dos 5.570 municípios brasileiros. Não utiliza PowerShell, Python, servidor local, chave de mapas ou instalação no computador do usuário.

## Abrir o protótipo

Abra `index.html` diretamente no navegador.

## Arquivos publicados

- `index.html`: tela principal do mapa do Brasil.
- `Mapa Rede Comgas.html`: mapa da rede de gás de São Paulo, aberto na mesma aba.
- `Arquivos do Mapa Brasil/Estilos do Mapa Brasil.css`: aparência do mapa do Brasil.
- `Arquivos do Mapa Brasil/Funcionamento do Mapa Brasil.js`: filtros, tabela e interações do mapa do Brasil.
- `Arquivos do Mapa Brasil/Dados`: dados municipais e recursos geográficos derivados da malha do IBGE.
- `Arquivos do Mapa SP`: estilos, funcionamento e biblioteca local do mapa de São Paulo.

O arquivo atualizado mensalmente é `Arquivos do Mapa Brasil/Dados/municipios-gn.js`. Os demais arquivos do mapa não devem ser substituídos durante a atualização mensal.

## Atualização mensal com Power Automate

1. Execute o Office Script `power-automate/OfficeScript-exportar-municipios.ts` no Excel consolidado.
2. Use a saída textual da ação **Executar script**.
3. Na pasta publicada do site, substitua o conteúdo de `4_Mapa_GN/Arquivos do Mapa Brasil/Dados/municipios-gn.js` pela saída.
4. Não altere o HTML nem a malha geográfica durante a atualização mensal.

O Office Script lê a aba `Tabular`, valida os cabeçalhos e converte `Atendido em expansão` para a categoria visual `Atendido`, preservando o valor original.

## Integração com a calculadora

Hospede esta pasta junto da calculadora e use um link relativo:

```html
<a href="../4_Mapa_GN/index.html">Consultar disponibilidade de GN</a>
```

O endereço definitivo dependerá da estrutura usada na publicação da calculadora.

