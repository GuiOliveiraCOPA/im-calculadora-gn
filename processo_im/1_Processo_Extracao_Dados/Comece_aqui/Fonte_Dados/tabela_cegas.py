from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import pandas as pd
import os
import sys
import time
from datetime import datetime

print("ðŸŒ CEGÃS - VERSÃƒO FINAL")

# Config headless
options = Options()
options.add_argument("--headless")
if sys.platform != "win32":
    # Servidor Linux sem interface grafica (AtualizarDados.sh): Chrome/Chromium precisa destas opcoes.
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    if os.environ.get("GN_CHROME_BINARY"):
        options.binary_location = os.environ["GN_CHROME_BINARY"]
driver = webdriver.Chrome(options=options)

dfs = []
try:
    print("ðŸ“„ Carregando...")
    driver.get("https://www.cegas.com.br/gas-natural/tabela-de-tarifas-atual-3/")
    time.sleep(5)
    
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)
    
    tabelas = driver.find_elements(By.TAG_NAME, "table")
    print(f"âœ… {len(tabelas)} tabelas")
    
    for i, tabela in enumerate(tabelas):
        try:
            linhas = tabela.find_elements(By.TAG_NAME, "tr")
            dados = []
            for linha in linhas:
                celulas = [td.text.strip() for td in linha.find_elements(By.TAG_NAME, "td")]
                if celulas:
                    dados.append(celulas)
            
            if len(dados) > 1:
                df = pd.DataFrame(dados)
                df = df.dropna(how='all')
                if len(df) > 0:
                    dfs.append(df)
                    print(f"  Tabela {i+1}: {len(df)} linhas")
        except:
            pass
    
    # SIMPLIFICADO - sem cabeÃ§alho problemÃ¡tico
    todas_tabelas = pd.DataFrame()
    for i, df in enumerate(dfs):
        todas_tabelas = pd.concat([todas_tabelas, df], ignore_index=True)
        todas_tabelas.loc[len(todas_tabelas)] = [f'--- CEGAS TABELA {i+1} ---'] + ['']* (len(df.columns)-1)
    
    todas_tabelas = todas_tabelas.dropna(how='all')

    from datetime import datetime
    data_hoje = datetime.now().strftime("%Y-%m-%d")
    output_file = f"Cegas_{data_hoje}.xlsx"
    todas_tabelas.to_excel(output_file, index=False, header=False)
    
    print(f"âœ… SALVO: {output_file}")
    print(f"ðŸ“Š {len(todas_tabelas)} linhas")
    
finally:
    driver.quit()

print("ðŸŽ‰ PRONTO!")
