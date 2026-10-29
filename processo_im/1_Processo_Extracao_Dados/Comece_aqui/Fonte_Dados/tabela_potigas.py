from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag


URL = "https://potigas.com.br/sistema-tarifario/vigente"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TARGET_TABLES: List[Tuple[str, int]] = [
    ("Industrial", 0),
    ("Comercial", 5),
    ("Residencial", 4),
]


def normalize(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).strip()


def get_soup() -> BeautifulSoup:
    session = requests.Session()
    session.trust_env = False
    response = session.get(URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def table_to_rows(table: Tag) -> List[List[str]]:
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = [normalize(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def rows_to_dataframe(rows: List[List[str]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    return pd.DataFrame(normalized_rows[1:], columns=normalized_rows[0])


def extract_blocks() -> List[Dict[str, object]]:
    soup = get_soup()
    tables = soup.find_all("table")
    blocks: List[Dict[str, object]] = []
    for title, index in TARGET_TABLES:
        if index >= len(tables):
            continue
        df = rows_to_dataframe(table_to_rows(tables[index]))
        if not df.empty:
            blocks.append({"titulo": title, "dataframe": df})
    return blocks


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        width = 10
        for cell in column_cells:
            if cell.value is not None:
                width = max(width, len(str(cell.value)) + 2)
        worksheet.column_dimensions[letter].width = min(width, 45)


def save_excel(blocks: List[Dict[str, object]], output_dir: Path) -> Path:
    output_path = output_dir / f"Potigas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        row_pointer = 0
        for block in blocks:
            pd.DataFrame([[block["titulo"]]], columns=["descricao"]).to_excel(writer, sheet_name="Tarifas", index=False, header=False, startrow=row_pointer)
            row_pointer += 2
            df = block["dataframe"]
            df.to_excel(writer, sheet_name="Tarifas", index=False, startrow=row_pointer)
            row_pointer += len(df) + 3
        pd.DataFrame([{"site": URL, "extraido_em": datetime.now().isoformat(timespec="seconds"), "blocos": len(blocks)}]).to_excel(writer, sheet_name="controle", index=False)
        autosize_columns(writer.sheets["Tarifas"])
        autosize_columns(writer.sheets["controle"])
    return output_path


def main() -> None:
    print("Buscando tabelas da Potigas...")
    blocks = extract_blocks()
    output = save_excel(blocks, Path.cwd())
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output}")


if __name__ == "__main__":
    main()
