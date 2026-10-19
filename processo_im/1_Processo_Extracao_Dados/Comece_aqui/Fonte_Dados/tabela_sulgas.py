import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag


HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGES = {
    "residencial": "https://www.sulgas.com.vc/residencial/",
    "comercial": "https://www.sulgas.com.vc/comercial/",
    "industrial": "https://www.sulgas.com.vc/industrial/",
}
RESIDENTIAL_TARGETS = {
    "Tabela - Unidade Unifamiliar": "Residencial Unifamiliar",
    "Tabela - Faturamento Coletivo": "Residencial - Faturamento Coletivo",
}


def normalize_text(value: str) -> str:
    value = str(value or "").replace("\xa0", " ")
    value = value.replace("mł", "m³")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def http_get(url: str, timeout: int = 60) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def fetch_html(url: str) -> str:
    return http_get(url).text


def convert_daily_range_text_to_monthly(value: str) -> str:
    value = normalize_text(value)
    if not value or "faixa unica" in value.lower():
        return value

    pattern = re.compile(r"\d[\d\.,]*")
    matches = pattern.findall(value)
    if not matches:
        return value

    converted = value
    for match in sorted(matches, key=len, reverse=True):
        digits = re.sub(r"[^\d]", "", match)
        if not digits:
            continue
        monthly = int(digits) * 30
        formatted = f"{monthly:,}".replace(",", ".")
        converted = converted.replace(match, formatted, 1)
    return converted


def table_to_rows(table: Tag) -> List[List[str]]:
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = [normalize_text(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    return rows


def classify_table(rows: List[List[str]]) -> pd.DataFrame:
    header = [normalize_text(value).lower() for value in rows[0]]
    data_rows = rows[1:]
    has_daily_range = any("/dia" in value for value in header)

    if len(header) >= 3 and (("fixo" in header[1]) or ("fixa" in header[1])) and "vari" in header[2]:
        data = []
        for row in data_rows:
            if len(row) >= 3:
                faixa = convert_daily_range_text_to_monthly(row[0]) if has_daily_range else row[0]
                data.append([faixa, row[1], row[2]])
        return pd.DataFrame(data, columns=["faixa_consumo_m3_mes", "tarifa_fixa_r$", "tarifa_variavel_r$_m3"])

    if len(header) >= 2 and ("tarifa" in header[1] or "(r$/m³)" in rows[0][1].lower()):
        data = []
        for row in data_rows:
            if len(row) >= 2:
                faixa = convert_daily_range_text_to_monthly(row[0]) if has_daily_range else row[0]
                data.append([faixa, row[1]])
        return pd.DataFrame(data, columns=["faixa_consumo_m3_mes", "tarifa_r$_m3"])

    max_cols = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (max_cols - len(row)) for row in rows]
    return pd.DataFrame(normalized_rows[1:], columns=normalized_rows[0])


def extract_residential_blocks() -> List[Dict[str, object]]:
    html = fetch_html(PAGES["residencial"])
    soup = BeautifulSoup(html, "html.parser")
    blocks: List[Dict[str, object]] = []

    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        summary_text = normalize_text(summary.get_text(" ", strip=True))
        if summary_text not in RESIDENTIAL_TARGETS:
            continue
        table = details.find("table")
        if not table:
            continue
        rows = table_to_rows(table)
        if len(rows) < 2:
            continue
        blocks.append(
            {
                "titulo": RESIDENTIAL_TARGETS[summary_text],
                "dataframe": classify_table(rows),
                "origem": PAGES["residencial"],
            }
        )

    return blocks


def extract_target_blocks() -> List[Dict[str, object]]:
    blocks: List[Dict[str, object]] = []
    blocks.extend(extract_residential_blocks())

    commercial_html = fetch_html(PAGES["comercial"])
    commercial_soup = BeautifulSoup(commercial_html, "html.parser")
    commercial_tables = commercial_soup.find_all("table")
    if commercial_tables:
        rows = table_to_rows(commercial_tables[0])
        blocks.append(
            {
                "titulo": "Comercial",
                "dataframe": classify_table(rows),
                "origem": PAGES["comercial"],
            }
        )

    industrial_html = fetch_html(PAGES["industrial"])
    industrial_soup = BeautifulSoup(industrial_html, "html.parser")
    industrial_tables = industrial_soup.find_all("table")
    if industrial_tables:
        rows = table_to_rows(industrial_tables[0])
        blocks.append(
            {
                "titulo": "Industrial",
                "dataframe": classify_table(rows),
                "origem": PAGES["industrial"],
            }
        )

    desired_order = [
        "Residencial Unifamiliar",
        "Residencial - Faturamento Coletivo",
        "Comercial",
        "Industrial",
    ]
    ordered: List[Dict[str, object]] = []
    for title in desired_order:
        for block in blocks:
            if block["titulo"] == title:
                ordered.append(block)
                break
    return ordered


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def save_excel(blocks: List[Dict[str, object]], output_dir: Path) -> Path:
    output_path = output_dir / f"Sulgas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        worksheet_name = "Tarifas"
        row_pointer = 0

        for block in blocks:
            header_block = pd.DataFrame(
                [
                    [str(block["titulo"])],
                    [str(block["origem"])],
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
                    "site_residencial": PAGES["residencial"],
                    "site_comercial": PAGES["comercial"],
                    "site_industrial": PAGES["industrial"],
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
    print("Buscando as paginas da Sulgas...")
    blocks = extract_target_blocks()
    if not blocks:
        raise RuntimeError("Nenhuma das tabelas desejadas foi encontrada na Sulgas.")

    output_path = save_excel(blocks, Path.cwd())

    print("Concluido.")
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()

