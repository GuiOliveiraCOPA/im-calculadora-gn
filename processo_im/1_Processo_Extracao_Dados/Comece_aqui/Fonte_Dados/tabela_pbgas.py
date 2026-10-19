import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag


SITE_URL = "https://pbgas.com.br/tarifas/"
HEADERS = {"User-Agent": "Mozilla/5.0"}

BLOCK_ORDER = [
    "Residencial",
    "Comercial",
    "Industrial",
    "Ceramico e Mineracao",
    "Poder Publico",
    "Calcadista",
]


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


def fetch_html() -> str:
    response = http_get(SITE_URL, timeout=60)
    return response.text


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


def extract_table_matrix(table: Tag) -> Tuple[List[List[str]], List[bool]]:
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


def build_headers(matrix: List[List[str]], header_flags: List[bool]) -> Tuple[List[str], int]:
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
        columns.append(" | ".join(parts) if parts else f"coluna_{column_index + 1}")

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


def find_block_title(table: Tag) -> str:
    node = table
    for _ in range(8):
        node = node.find_previous(lambda t: isinstance(t, Tag) and t.name in ["h1", "h2", "h3", "h4", "h5"])
        if not node:
            break
        title = normalize_ascii(normalize_text(node.get_text(" ", strip=True)))
        if title:
            return title
    return "Tabela"


def is_relevant_title(title: str) -> bool:
    normalized = normalize_ascii(title).lower()
    ignored = ["veicular", "comprimido", "ebva", "geracao distribuida"]
    if any(term in normalized for term in ignored):
        return False
    return any(term in normalized for term in [normalize_ascii(name).lower() for name in BLOCK_ORDER])


def sort_priority(title: str) -> int:
    normalized = normalize_ascii(title).lower()
    for index, block in enumerate(BLOCK_ORDER):
        if normalize_ascii(block).lower() in normalized:
            return index
    return 99


def extract_relevant_tables(html: str) -> List[Dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    extracted: List[Dict[str, object]] = []

    for table in tables:
        title = find_block_title(table)
        if not is_relevant_title(title):
            continue

        df = table_to_dataframe(table)
        if df.empty:
            continue

        extracted.append({"titulo": title, "dataframe": df})

    if not extracted:
        raise RuntimeError("Nenhuma tabela relevante foi encontrada na pagina da PBGas.")

    extracted.sort(key=lambda item: sort_priority(str(item["titulo"])))
    return extracted


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def save_excel(blocks: List[Dict[str, object]], output_dir: Path) -> Path:
    output_path = output_dir / f"Pbgas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

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
    print("Buscando a pagina de tarifas da PBGas...")
    html = fetch_html()

    print("Extraindo as tabelas relevantes...")
    blocks = extract_relevant_tables(html)

    output_path = save_excel(blocks, Path.cwd())

    print("Concluido.")
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()
