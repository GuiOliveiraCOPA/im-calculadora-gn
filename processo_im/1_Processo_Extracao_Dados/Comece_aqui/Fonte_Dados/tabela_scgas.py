import re
import unicodedata
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup


SITE_URL = "https://www.scgas.com.br/scgas/site/a-scgas/publicacoes-das-tarifas"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TARGET_PDF_TEXT = "DOESC 31/12/2025"


def normalize_text(value: str) -> str:
    value = str(value or "").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def http_get(url: str, timeout: int) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def parse_br_number(value: str) -> float:
    return float(value.replace(".", "").replace(",", "."))


def format_br_integer(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", ".")


def convert_range_text_to_monthly(value: str) -> str:
    value = normalize_text(value)
    if not value:
        return value

    normalized = normalize_ascii(value).lower()
    if "unica" in normalized:
        return value

    pattern = re.compile(r"\d[\d\.]*")
    matches = pattern.findall(value)
    if not matches:
        return value

    converted = value
    for match in sorted(matches, key=len, reverse=True):
        monthly = format_br_integer(parse_br_number(match) * 30)
        converted = converted.replace(match, monthly, 1)

    return converted


def fetch_publications_html() -> str:
    response = http_get(SITE_URL, timeout=60)
    return response.text


def find_latest_tariff_pdf_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        text = normalize_text(anchor.get_text(" ", strip=True))
        if TARGET_PDF_TEXT in text:
            return urljoin(SITE_URL, anchor["href"])

    raise RuntimeError("Nao foi possivel localizar a publicacao tarifaria vigente da SCGas.")


def fetch_pdf_tables(pdf_url: str) -> List[List[List[str]]]:
    response = http_get(pdf_url, timeout=120)
    with pdfplumber.open(BytesIO(response.content)) as pdf:
        if not pdf.pages:
            raise RuntimeError("O PDF da SCGas nao possui paginas legiveis.")
        tables = pdf.pages[0].extract_tables()
        if not tables:
            raise RuntimeError("Nao foi possivel extrair tabelas do PDF da SCGas.")
        return [[[normalize_text(cell) for cell in row] for row in table] for table in tables]


def rows_to_dataframe(rows: List[List[str]], columns: List[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def convert_daily_rows_to_monthly(rows: List[List[str]]) -> List[List[str]]:
    converted: List[List[str]] = []
    for row in rows:
        new_row = row.copy()
        if new_row:
            new_row[0] = convert_range_text_to_monthly(new_row[0])
        converted.append(new_row)
    return converted


def build_blocks_from_tables(tables: List[List[List[str]]]) -> List[Dict[str, object]]:
    index_map = {
        "Residencial": 8,
        "Comercial": 4,
        "Industrial TG1": 7,
        "Industrial TG2": 11,
        "Industrial TG3": 14,
        "Materia Prima": 5,
    }

    blocks: List[Dict[str, object]] = []

    residencial_rows = [tables[index_map["Residencial"]][1]]
    residencial_df = rows_to_dataframe(
        residencial_rows,
        ["faixa_mensal", "pv_pr_r$_m3", "margem_bruta_r$_m3", "tributos_r$_m3", "tarifa_bruta_r$_m3"],
    )
    blocks.append({"titulo": "Residencial", "dataframe": residencial_df})

    comercial_rows = tables[index_map["Comercial"]][2:]
    comercial_df = rows_to_dataframe(
        comercial_rows,
        ["faixa_consumo_m3_mes", "pv_pr_r$_m3", "margem_bruta_r$_m3", "tributos_r$_m3", "tarifa_bruta_r$_m3"],
    )
    blocks.append({"titulo": "Comercial", "dataframe": comercial_df})

    for title in ["Industrial TG1"]:
        rows = tables[index_map[title]][2:]
        rows = convert_daily_rows_to_monthly(rows)
        df = rows_to_dataframe(
            rows,
            ["faixa_consumo_m3_mes", "pv_pr_r$_m3", "margem_bruta_r$_m3", "tributos_r$_m3", "tarifa_bruta_r$_m3"],
        )
        blocks.append({"titulo": title, "dataframe": df})

    return blocks


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def save_excel(blocks: List[Dict[str, object]], pdf_url: str, output_dir: Path) -> Path:
    output_path = output_dir / f"Scgas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        worksheet_name = "Tarifas"
        row_pointer = 0

        for block in blocks:
            header_block = pd.DataFrame(
                [
                    [str(block["titulo"])],
                    ["Faixas diarias convertidas para m3/mes quando aplicavel"],
                ],
                columns=["descricao"],
            )
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
                }
            ]
        )
        metadata.to_excel(writer, sheet_name="controle", index=False)

        autosize_columns(writer.sheets[worksheet_name])
        autosize_columns(writer.sheets["controle"])

    return output_path


def main() -> None:
    print("Buscando a pagina de publicacoes tarifarias da SCGas...")
    html = fetch_publications_html()

    print("Localizando a publicacao tarifaria vigente...")
    pdf_url = find_latest_tariff_pdf_url(html)
    print(f"PDF selecionado: {pdf_url}")

    print("Extraindo tabelas do PDF...")
    tables = fetch_pdf_tables(pdf_url)
    blocks = build_blocks_from_tables(tables)

    output_path = save_excel(blocks, pdf_url, Path.cwd())

    print("Concluido.")
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()

