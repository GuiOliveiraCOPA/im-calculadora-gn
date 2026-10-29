import re
import os
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from requests import RequestException
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions


SITE_URL = "https://msgas.com.br/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
ANNEX_PATTERN = re.compile(r"^ANEXO\s+([IVX]+)\s+.*PORTARIA", re.IGNORECASE)

TARGET_ANNEXES = ["I", "II", "III", "IX"]
MONTHLY_CONVERSION_ANNEXES = {"I", "III", "IX"}


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def is_numeric_token(token: str) -> bool:
    return bool(re.fullmatch(r"-?\d[\d\.,]*", token))


def parse_br_number(value: str) -> float:
    return float(value.replace(".", "").replace(",", "."))


def decimal_places(value: str) -> int:
    if "," not in value:
        return 0
    return len(value.rsplit(",", 1)[1])


def format_br_number(value: float, places: int) -> str:
    formatted = f"{value:,.{places}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def multiply_consumption_by_30(value: str) -> str:
    if not is_numeric_token(value):
        return value

    places = decimal_places(value)
    converted = parse_br_number(value) * 30
    return format_br_number(converted, places)


def fetch_home_html() -> str:
    try:
        response = requests.get(
            SITE_URL,
            headers={
                **HEADERS,
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
                "Referer": SITE_URL,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.text
    except RequestException:
        return fetch_home_html_with_browser()


def fetch_home_html_with_browser() -> str:
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

    raise RuntimeError(f"Nao foi possivel carregar o site da MSGas. Detalhes: {' | '.join(errors)}")


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


def find_tariff_pdf_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    pdf_urls: List[str] = []

    for anchor in soup.find_all("a", href=True):
        text = normalize_text(anchor.get_text(" ", strip=True)).lower()
        absolute_url = urljoin(SITE_URL, anchor["href"])
        if "tarifa" not in text and "tarifa" not in absolute_url.lower():
            continue
        if ".pdf" not in absolute_url.lower():
            continue
        if absolute_url not in pdf_urls:
            pdf_urls.append(absolute_url)

    if not pdf_urls:
        raise RuntimeError("Nao foi possivel localizar o PDF de tarifas no site da MSGas.")

    return pdf_urls[0]


def fetch_pdf_bytes(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, headers=HEADERS, timeout=120)
    response.raise_for_status()
    return response.content


def extract_pdf_lines(pdf_bytes: bytes) -> List[str]:
    lines: List[str] = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = normalize_text(raw_line)
                if line:
                    lines.append(line)

    return lines


def should_ignore_line(line: str) -> bool:
    ignored_starts = [
        "DiÃ¡rio Oficial EletrÃ´nico",
        "A autenticidade deste documento",
        "Companhia de GÃ¡s do Estado",
        "PORTARIA NÂº 016/2026",
    ]
    return any(line.startswith(prefix) for prefix in ignored_starts)


def split_annex_sections(lines: List[str]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current_annex: Optional[str] = None

    for line in lines:
        if should_ignore_line(line):
            continue
        if line.startswith("Departamento Estadual de TrÃ¢nsito"):
            break

        match = ANNEX_PATTERN.match(line)
        if match:
            current_annex = match.group(1).upper()
            sections.setdefault(current_annex, []).append(line)
            continue

        if current_annex is not None:
            sections[current_annex].append(line)

    missing = [annex for annex in TARGET_ANNEXES if annex not in sections]
    if missing:
        raise RuntimeError(f"Nao foi possivel localizar os anexos: {', '.join(missing)}")

    return sections


def parse_range_line(line: str) -> Optional[List[str]]:
    tokens = line.split()
    if len(tokens) < 4 or not is_numeric_token(tokens[0]):
        return None
    if not is_numeric_token(tokens[2]) or not is_numeric_token(tokens[3]):
        return None

    return [tokens[0], tokens[1], tokens[2], tokens[3]]


def collect_range_rows(section_lines: List[str]) -> List[List[str]]:
    rows: List[List[str]] = []

    for line in section_lines:
        parsed = parse_range_line(line)
        if parsed:
            rows.append(parsed)

    if not rows:
        raise RuntimeError("Nenhuma linha de faixa foi encontrada para a tabela esperada.")

    return rows


def convert_consumption_rows_to_monthly(rows: List[List[str]]) -> List[List[str]]:
    converted_rows: List[List[str]] = []

    for row in rows:
        converted_rows.append(
            [
                multiply_consumption_by_30(row[0]),
                multiply_consumption_by_30(row[1]),
                row[2],
                row[3],
            ]
        )

    return converted_rows


def business_title_for_annex(annex_id: str) -> str:
    titles = {
        "I": "Residencia coletiva",
        "II": "Residencia individual",
        "III": "Comercial e Industrial de Menor Consumo",
        "IX": "Industrial - Sobredemanda",
    }
    return titles[annex_id]


def parse_target_annexes(sections: Dict[str, List[str]]) -> List[Dict[str, object]]:
    tables: List[Dict[str, object]] = []

    for annex_id in TARGET_ANNEXES:
        rows = collect_range_rows(sections[annex_id])
        unit = "m3_mes"

        if annex_id in MONTHLY_CONVERSION_ANNEXES:
            rows = convert_consumption_rows_to_monthly(rows)

        df = pd.DataFrame(
            rows,
            columns=[
                f"faixa_inicial_{unit}",
                f"faixa_final_{unit}",
                "tarifa_sem_impostos_r$_m3",
                "tarifa_com_impostos_r$_m3",
            ],
        )

        tables.append(
            {
                "anexo": f"ANEXO {annex_id}",
                "titulo": business_title_for_annex(annex_id),
                "dataframe": df,
            }
        )

    return tables


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def save_excel(tables: List[Dict[str, object]], pdf_url: str, output_dir: Path) -> Path:
    output_path = output_dir / f"Msgas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        worksheet_name = "Tarifas"
        row_pointer = 0

        for entry in tables:
            header_block = pd.DataFrame(
                [
                    [str(entry["anexo"])],
                    [str(entry["titulo"])],
                    ["Faixas convertidas para m3/mes"],
                ],
                columns=["descricao"],
            )
            header_block.to_excel(writer, sheet_name=worksheet_name, index=False, header=False, startrow=row_pointer)
            row_pointer += len(header_block) + 1

            df = entry["dataframe"]
            df.to_excel(writer, sheet_name=worksheet_name, index=False, startrow=row_pointer)
            row_pointer += len(df) + 3

        metadata = pd.DataFrame(
            [
                {
                    "site": SITE_URL,
                    "pdf_url": pdf_url,
                    "extraido_em": datetime.now().isoformat(timespec="seconds"),
                    "quantidade_tabelas": len(tables),
                    "observacao": "Faixas em m3/dia foram multiplicadas por 30; o Anexo II ja estava em m3/mes.",
                }
            ]
        )
        metadata.to_excel(writer, sheet_name="controle", index=False)

        autosize_columns(writer.sheets[worksheet_name])
        autosize_columns(writer.sheets["controle"])

    return output_path


def main() -> None:
    print("Buscando o site da MSGas...")
    html = fetch_home_html()

    print("Localizando o PDF de tarifas...")
    pdf_url = find_tariff_pdf_url(html)
    print(f"PDF selecionado: {pdf_url}")

    print("Lendo PDF em memoria...")
    pdf_bytes = fetch_pdf_bytes(pdf_url)
    lines = extract_pdf_lines(pdf_bytes)

    print("Separando os anexos relevantes...")
    sections = split_annex_sections(lines)

    print("Extraindo tabelas e convertendo consumo diario para mensal...")
    tables = parse_target_annexes(sections)

    output_path = save_excel(tables, pdf_url, Path.cwd())

    print("Concluido.")
    print(f"Tabelas encontradas: {len(tables)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()



