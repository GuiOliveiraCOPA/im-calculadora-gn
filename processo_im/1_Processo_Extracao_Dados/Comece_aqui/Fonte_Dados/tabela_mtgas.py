import re
import os
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from requests import RequestException
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions


SITE_URL = "https://mtgas.com.br/tarifas/"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def normalize_text(value: str) -> str:
    value = str(value or "").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()



def http_get(url: str, timeout: int) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response
def clean_numeric_range(value: str) -> str:
    value = normalize_text(value)
    if value in {"", "N/A", "-"}:
        return value

    value = re.sub(r"(?<=\d)\s+(?=\d)", "", value)
    return value


def fetch_tariff_page_html() -> str:
    try:
        response = http_get(SITE_URL, timeout=60)
        return response.text
    except RequestException:
        return fetch_html_with_browser()

def fetch_html_with_browser() -> str:
    errors: List[str] = []

    for browser_name in (("edge", "chrome") if sys.platform == "win32" else ("chrome",)):
        try:
            driver = build_driver(browser_name)
            try:
                driver.get(SITE_URL)
                time.sleep(3)
                scroll_page(driver)
                return driver.page_source
            finally:
                driver.quit()
        except Exception as exc:
            errors.append(f"{browser_name}: {exc}")

    raise RuntimeError(f"Nao foi possivel carregar a pagina da MTGas. Detalhes: {' | '.join(errors)}")


def build_driver(browser_name: str):
    if browser_name == "edge":
        options = EdgeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1600,2400")
        options.add_argument("--log-level=3")
        return webdriver.Edge(options=options)

    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,2400")
    options.add_argument("--log-level=3")
    if sys.platform != "win32":
        # Servidor Linux sem interface grafica (AtualizarDados.sh): Chrome/Chromium precisa destas opcoes.
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        if os.environ.get("GN_CHROME_BINARY"):
            options.binary_location = os.environ["GN_CHROME_BINARY"]
    return webdriver.Chrome(options=options)


def scroll_page(driver) -> None:
    previous_height = 0
    for _ in range(10):
        current_height = driver.execute_script("return document.body.scrollHeight")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.2)
        if current_height == previous_height:
            break
        previous_height = current_height


def find_latest_tariff_pdf_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    candidates: List[str] = []

    for anchor in soup.find_all("a", href=True):
        text = normalize_text(anchor.get_text(" ", strip=True)).lower()
        href = urljoin(SITE_URL, anchor["href"])
        if ".pdf" not in href.lower():
            continue
        if "tarifa" not in text and "tarifa" not in href.lower():
            continue
        if "vigente" not in text and "vigente" not in href.lower():
            continue
        if href not in candidates:
            candidates.append(href)

    if not candidates:
        raise RuntimeError("Nao foi possivel localizar o PDF tarifario vigente da MTGas.")

    return candidates[0]


def extract_html_table(html: str) -> Optional[List[List[str]]]:
    # Desde 10/2026 a MTGas publica a tarifa vigente como tabela HTML na pagina,
    # com as mesmas colunas e as mesmas 2 linhas de cabecalho do PDF antigo.
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows = [
            [normalize_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
            for tr in table.find_all("tr")
        ]
        header = " ".join(" ".join(row) for row in rows[:2]).lower()
        if "segmento" in header and "total s/ imp" in header:
            return rows
    return None


def find_validity_title(html: str) -> str:
    text = normalize_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    match = re.search(r"TARIFA VIGENTE A PARTIR DE \d{2}/\d{2}/\d{4}", text, flags=re.IGNORECASE)
    return match.group(0) if match else ""


def fetch_pdf_bytes(pdf_url: str) -> bytes:
    response = http_get(pdf_url, timeout=120)
    return response.content

def extract_pdf_table(pdf_bytes: bytes) -> List[List[str]]:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        if not pdf.pages:
            raise RuntimeError("O PDF da MTGas nao possui paginas legiveis.")

        table = pdf.pages[0].extract_table()
        if not table:
            raise RuntimeError("Nao foi possivel extrair a tabela do PDF da MTGas.")

        return [[normalize_text(cell) for cell in row] for row in table]


def build_relevant_blocks(table_rows: List[List[str]]) -> List[Dict[str, object]]:
    if len(table_rows) < 3:
        raise RuntimeError("A tabela da MTGas nao possui linhas suficientes para extracao.")

    data_rows = table_rows[2:]
    blocks: Dict[str, List[Dict[str, str]]] = {
        "Residencial": [],
        "Comercial e Industrial": [],
        "Industrial Fertilizantes": [],
    }

    for row in data_rows:
        if len(row) < 9:
            continue

        segmento = normalize_text(row[0])
        faixa_min = clean_numeric_range(row[1])
        faixa_max = clean_numeric_range(row[2])

        parsed_row = {
            "faixa_min_m3_mes": faixa_min,
            "faixa_max_m3_mes": faixa_max,
            "preco_gas_e_transporte_r$_m3": normalize_text(row[3]),
            "margem_distribuicao_r$_m3": normalize_text(row[4]),
            "irpgt_r$_m3": normalize_text(row[5]),
            "total_sem_impostos_r$_m3": normalize_text(row[6]),
            "impostos_r$_m3": normalize_text(row[7]),
            "total_com_impostos_r$_m3": normalize_text(row[8]),
        }

        normalized_segment = segmento.lower()
        if normalized_segment == "residencial":
            blocks["Residencial"].append(parsed_row)
        elif normalized_segment.startswith("industrial/comerc"):
            blocks["Comercial e Industrial"].append(parsed_row)
        elif normalized_segment.startswith("industrial fertilizantes"):
            blocks["Industrial Fertilizantes"].append(parsed_row)

    result: List[Dict[str, object]] = []
    for title in ["Residencial", "Comercial e Industrial", "Industrial Fertilizantes"]:
        rows = blocks[title]
        if not rows:
            continue
        result.append({"titulo": title, "dataframe": pd.DataFrame(rows)})

    if not result:
        raise RuntimeError("Nenhum bloco relevante foi encontrado na tabela da MTGas.")

    return result


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def save_excel(blocks: List[Dict[str, object]], pdf_url: str, output_dir: Path, fonte: str = "PDF", vigencia: str = "") -> Path:
    output_path = output_dir / f"Mtgas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        worksheet_name = "Tarifas"
        row_pointer = 0

        for block in blocks:
            header_block = pd.DataFrame([[str(block["titulo"])]], columns=["descricao"])
            header_block.to_excel(writer, sheet_name=worksheet_name, index=False, header=False, startrow=row_pointer)
            row_pointer += len(header_block) + 1

            df = block["dataframe"]
            df.to_excel(writer, sheet_name=worksheet_name, index=False, startrow=row_pointer)
            row_pointer += len(df) + 3

        metadata = pd.DataFrame(
            [
                {
                    "site": SITE_URL,
                    "pdf_url": pdf_url,
                    "extraido_em": datetime.now().isoformat(timespec="seconds"),
                    "quantidade_blocos": len(blocks),
                    "fonte": fonte,
                    "vigencia": vigencia,
                }
            ]
        )
        metadata.to_excel(writer, sheet_name="controle", index=False)

        autosize_columns(writer.sheets[worksheet_name])
        autosize_columns(writer.sheets["controle"])

    return output_path


def main() -> None:
    print("Buscando a pagina de tarifas da MTGas...")
    html = fetch_tariff_page_html()

    print("Procurando a tabela de tarifa vigente na pagina...")
    table_rows = extract_html_table(html)
    if table_rows:
        fonte = "HTML da pagina"
        pdf_url = ""
        vigencia = find_validity_title(html)
        print(f"Tabela encontrada na pagina. {vigencia}")
    else:
        print("Tabela nao encontrada na pagina. Localizando o PDF tarifario vigente...")
        fonte = "PDF"
        vigencia = ""
        pdf_url = find_latest_tariff_pdf_url(html)
        print(f"PDF selecionado: {pdf_url}")

        print("Lendo o PDF em memoria...")
        pdf_bytes = fetch_pdf_bytes(pdf_url)

        print("Extraindo a tabela do PDF...")
        table_rows = extract_pdf_table(pdf_bytes)

    blocks = build_relevant_blocks(table_rows)

    output_path = save_excel(blocks, pdf_url, Path.cwd(), fonte, vigencia)

    print("Concluido.")
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()