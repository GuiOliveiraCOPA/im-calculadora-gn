import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag


SITE_URL = "https://www.sergipegas.com.br/tarifas"
HEADERS = {"User-Agent": "Mozilla/5.0"}


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
    return http_get(SITE_URL, timeout=60).text


def find_table_title(table: Tag) -> str:
    node = table
    for _ in range(12):
        node = node.find_previous(lambda t: isinstance(t, Tag) and t.name in ["h1", "h2", "h3", "h4", "h5", "p", "strong"])
        if not node:
            break
        text = normalize_ascii(normalize_text(node.get_text(" ", strip=True)))
        if text.startswith("Tarifa para o segmento"):
            return text
    return "Tabela"


def dedupe_adjacent(values: List[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result


def table_to_rows(table: Tag) -> List[List[str]]:
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = [normalize_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        cells = [cell for cell in cells if cell]
        if not cells:
            continue
        rows.append(dedupe_adjacent(cells))
    return rows


def title_alias(title: str) -> str:
    normalized = normalize_ascii(title).lower()
    if "residencial" in normalized:
        return "Residencial"
    if "comercial" in normalized:
        return "Comercial"
    if normalized == "tarifa para o segmento industrial":
        return "Industrial"
    return title


def classify_table(rows: List[List[str]], title: str) -> pd.DataFrame:
    normalized_title = normalize_ascii(title).lower()

    if "residencial" in normalized_title:
        value_row = rows[-1]
        return pd.DataFrame(
            [[value_row[-2], value_row[-1]]],
            columns=["tarifa_ex_tributos_r$_m3", "tarifa_com_impostos_r$_m3"],
        )

    if "comercial" in normalized_title:
        data = []
        for row in rows[1:]:
            if len(row) >= 4:
                data.append([row[0], row[1], row[2], row[3]])
        return pd.DataFrame(
            data,
            columns=[
                "faixa_consumo_min_m3_mes",
                "faixa_consumo_max_m3_mes",
                "tarifa_ex_tributos_r$_m3",
                "tarifa_com_impostos_r$_m3",
            ],
        )

    if normalized_title == "tarifa para o segmento industrial":
        data = []
        for row in rows[1:]:
            if len(row) >= 4:
                data.append([row[0], row[1], row[2], row[3]])
        return pd.DataFrame(
            data,
            columns=[
                "faixa_consumo_min_m3_semana",
                "faixa_consumo_max_m3_semana",
                "tarifa_ex_tributos_r$_m3",
                "tarifa_com_impostos_r$_m3",
            ],
        )

    raise RuntimeError(f"Tabela nao suportada: {title}")


def extract_relevant_blocks(html: str) -> List[Dict[str, object]]:
    soup = BeautifulSoup(html, "html.parser")
    blocks: List[Dict[str, object]] = []
    seen_titles = set()

    for table in soup.find_all("table"):
        title = find_table_title(table)
        normalized = normalize_ascii(title).lower()
        if normalized not in {
            "tarifa para o segmento residencial",
            "tarifa para o segmento comercial",
            "tarifa para o segmento industrial",
        }:
            continue

        alias = title_alias(title)
        if alias in seen_titles:
            continue

        rows = table_to_rows(table)
        df = classify_table(rows, title)
        blocks.append({"titulo": alias, "dataframe": df})
        seen_titles.add(alias)

    order = {"Residencial": 0, "Comercial": 1, "Industrial": 2}
    blocks.sort(key=lambda item: order.get(str(item["titulo"]), 99))
    return blocks


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def save_excel(blocks: List[Dict[str, object]], output_dir: Path) -> Path:
    output_path = output_dir / f"Sergipegas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

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
            [{
                "site": SITE_URL,
                "extraido_em": datetime.now().isoformat(timespec="seconds"),
                "quantidade_blocos": len(blocks),
            }]
        )
        metadata.to_excel(writer, sheet_name="controle", index=False)

        autosize_columns(writer.sheets[worksheet_name])
        autosize_columns(writer.sheets["controle"])

    return output_path


def main() -> None:
    print("Buscando a pagina de tarifas da Sergipe Gas...")
    html = fetch_html()

    print("Extraindo as tabelas relevantes...")
    blocks = extract_relevant_blocks(html)

    output_path = save_excel(blocks, Path.cwd())

    print("Concluido.")
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()

