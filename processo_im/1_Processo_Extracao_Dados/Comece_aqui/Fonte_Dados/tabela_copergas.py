import re
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag
from requests import RequestException
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions


PORTAL_URL = "https://copergas.com.br/informacoes/tarifas/"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_html() -> str:
    try:
        response = requests.get(
            PORTAL_URL,
            headers={
                **HEADERS,
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
                "Referer": "https://copergas.com.br/",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.text
    except RequestException:
        return fetch_html_with_browser()


def fetch_html_with_browser() -> str:
    browser_errors: List[str] = []

    for browser_name in (("edge", "chrome") if sys.platform == "win32" else ("chrome",)):
        try:
            driver = build_driver(browser_name)
            try:
                driver.get(PORTAL_URL)
                time.sleep(3)
                scroll_page(driver)
                wait_for_tables(driver)
                return driver.page_source
            finally:
                driver.quit()
        except Exception as exc:
            browser_errors.append(f"{browser_name}: {exc}")

    joined_errors = " | ".join(browser_errors)
    raise RuntimeError(f"Nao foi possivel carregar a pagina da Copergas. Detalhes: {joined_errors}")


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


def wait_for_tables(driver) -> None:
    for _ in range(20):
        tables = driver.find_elements(By.TAG_NAME, "table")
        if tables:
            return
        time.sleep(1)

    raise WebDriverException("Nenhuma tabela foi localizada na pagina apos o carregamento.")


def flatten_columns(columns: pd.Index) -> List[str]:
    flat_columns: List[str] = []

    for column in columns.tolist():
        if isinstance(column, tuple):
            parts = [normalize_text(str(part)) for part in column if normalize_text(str(part))]
            flat_columns.append(" | ".join(dict.fromkeys(parts)))
        else:
            flat_columns.append(normalize_text(str(column)))

    cleaned: List[str] = []
    for index, column in enumerate(flat_columns, start=1):
        name = column if column and not column.lower().startswith("unnamed") else f"coluna_{index}"
        cleaned.append(name)

    return cleaned


def expand_row_with_spans(
    cells: List[Tag],
    active_rowspans: Dict[int, Dict[str, object]],
) -> List[str]:
    row: List[str] = []
    column_index = 0

    def fill_rowspans_until_next_free_column() -> None:
        nonlocal column_index
        while column_index in active_rowspans:
            span_info = active_rowspans[column_index]
            row.append(str(span_info["text"]))
            span_info["remaining"] = int(span_info["remaining"]) - 1
            if span_info["remaining"] <= 0:
                del active_rowspans[column_index]
            column_index += 1

    fill_rowspans_until_next_free_column()

    for cell in cells:
        fill_rowspans_until_next_free_column()

        text = normalize_text(cell.get_text(" ", strip=True))
        rowspan = int(cell.get("rowspan", 1))
        colspan = int(cell.get("colspan", 1))

        for offset in range(colspan):
            row.append(text)
            if rowspan > 1:
                active_rowspans[column_index + offset] = {"text": text, "remaining": rowspan - 1}

        column_index += colspan

    fill_rowspans_until_next_free_column()
    return row


def extract_table_matrix(table: Tag) -> tuple[List[List[str]], List[bool]]:
    matrix: List[List[str]] = []
    header_flags: List[bool] = []
    active_rowspans: Dict[int, Dict[str, object]] = {}

    for row_tag in table.find_all("tr"):
        cells = row_tag.find_all(["th", "td"], recursive=False)
        if not cells:
            continue

        matrix.append(expand_row_with_spans(cells, active_rowspans))
        header_flags.append(all(cell.name == "th" for cell in cells))

    if not matrix:
        return [], []

    max_columns = max(len(row) for row in matrix)
    normalized_matrix = [row + [""] * (max_columns - len(row)) for row in matrix]
    return normalized_matrix, header_flags


def build_headers(matrix: List[List[str]], header_flags: List[bool]) -> tuple[List[str], int]:
    header_rows = 0
    for is_header in header_flags:
        if not is_header:
            break
        header_rows += 1

    if header_rows == 0:
        columns = [f"coluna_{index}" for index in range(1, len(matrix[0]) + 1)]
        return columns, 0

    columns: List[str] = []
    for column_index in range(len(matrix[0])):
        parts: List[str] = []
        for header_row_index in range(header_rows):
            part = normalize_text(matrix[header_row_index][column_index])
            if part and part not in parts:
                parts.append(part)

        column_name = " | ".join(parts) if parts else f"coluna_{column_index + 1}"
        columns.append(column_name)

    return columns, header_rows


def table_to_dataframe(table: Tag) -> pd.DataFrame:
    matrix, header_flags = extract_table_matrix(table)
    if not matrix:
        return pd.DataFrame()

    columns, data_start_index = build_headers(matrix, header_flags)
    data_rows = matrix[data_start_index:]
    if not data_rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(data_rows, columns=columns)
    df = df.fillna("")
    df = df.apply(lambda column: column.map(lambda value: normalize_text(str(value))))
    df = df.loc[~(df == "").all(axis=1)]
    return df.reset_index(drop=True)


def find_content_root(soup: BeautifulSoup) -> Tag:
    candidates = [
        soup.find("main"),
        soup.find("article"),
        soup.find("div", class_=re.compile("content|entry|post", re.IGNORECASE)),
        soup.body,
    ]

    for candidate in candidates:
        if isinstance(candidate, Tag):
            return candidate

    raise RuntimeError("Nao foi possivel localizar o conteudo principal da pagina.")


def extract_tables_with_context(html: str) -> List[Dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    root = find_content_root(soup)

    contexts: Dict[str, str] = {"h2": "", "h3": "", "h4": "", "h5": ""}
    current_vigency = ""
    collected: List[Dict[str, object]] = []

    for element in root.descendants:
        if not isinstance(element, Tag):
            continue

        if element.name in contexts:
            text = normalize_text(element.get_text(" ", strip=True))
            contexts[element.name] = text

            if element.name == "h3" and "historico de tarifas" in text.lower():
                break

            if "vigencia:" in text.lower():
                current_vigency = text
            continue

        if element.name != "table":
            continue

        section_title = contexts.get("h3", "")
        subsection_title = contexts.get("h4", "")
        detail_title = contexts.get("h5", "")
        joined_context = " | ".join(
            part for part in [section_title, subsection_title, detail_title, current_vigency] if part
        )

        if "historico de tarifas" in joined_context.lower():
            continue

        df = table_to_dataframe(element)
        if df.empty:
            continue

        text_blob = " ".join(df.astype(str).values.flatten()).lower()
        if "download" in text_blob and len(df.columns) <= 2:
            continue

        collected.append(
            {
                "title": subsection_title or section_title or f"Tabela {len(collected) + 1}",
                "detail": detail_title,
                "vigency": current_vigency,
                "dataframe": df,
            }
        )

    if not collected:
        raise RuntimeError("Nenhuma tabela foi encontrada na pagina da Copergas.")

    return collected


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 40)


def save_excel(tables: List[Dict[str, object]], output_dir: Path) -> Path:
    output_path = output_dir / f"Copergas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        row_pointer = 0
        worksheet_name = "Tarifas"

        for index, entry in enumerate(tables, start=1):
            title = str(entry["title"])
            detail = str(entry["detail"])
            vigency = str(entry["vigency"])
            df = entry["dataframe"]

            header_block = pd.DataFrame(
                [
                    [f"Tabela {index}"],
                    [title],
                    [detail] if detail else [""],
                    [vigency] if vigency else [""],
                ],
                columns=["descricao"],
            )
            header_block.to_excel(writer, sheet_name=worksheet_name, index=False, header=False, startrow=row_pointer)
            row_pointer += len(header_block)

            df.to_excel(writer, sheet_name=worksheet_name, index=False, startrow=row_pointer)
            row_pointer += len(df) + 3

        metadata = pd.DataFrame(
            [
                {
                    "site": PORTAL_URL,
                    "extraido_em": datetime.now().isoformat(timespec="seconds"),
                    "quantidade_tabelas": len(tables),
                }
            ]
        )
        metadata.to_excel(writer, sheet_name="controle", index=False)

        autosize_columns(writer.sheets[worksheet_name])
        autosize_columns(writer.sheets["controle"])

    return output_path


def main() -> None:
    print("Buscando tabelas no portal da Copergas...")
    html = fetch_html()

    print("Extraindo tabelas da pagina...")
    tables = extract_tables_with_context(html)

    output_path = save_excel(tables, Path.cwd())

    print("Concluido.")
    print(f"Tabelas encontradas: {len(tables)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()
