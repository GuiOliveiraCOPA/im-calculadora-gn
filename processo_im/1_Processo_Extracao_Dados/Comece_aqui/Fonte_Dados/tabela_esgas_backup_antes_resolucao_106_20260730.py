import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup


PORTAL_URL = "https://arsp.es.gov.br/gas/tarifas/ESGas/tarifavigente"
TARGET_TITLE = "Decisão ARSP/DG Nº 003 de 20 de abril de 2026"
HEADERS = {"User-Agent": "Mozilla/5.0"}

SEGMENTS = [
    "Residencial - Medição Individual",
    "Residencial - Medição Coletiva",
    "Comercial",
    "Industrial",
    "Cogeração e Climatização",
    "GNV - (Postos e Frotas)",
    "Matéria Prima",
]


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_number_text(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"(?<=\d)\s+(?=[\d\.,])", "", value)
    value = re.sub(r"(?<=[\d\.,])\s+(?=\d)", "", value)
    value = value.replace(" ", "")
    return value


def format_number_two_decimals(value: str) -> str:
    value = normalize_number_text(value)
    if not value:
        return ""

    negative = value.startswith("-")
    normalized = value[1:] if negative else value
    normalized = normalized.replace(".", "").replace(",", ".")

    try:
        number = float(normalized)
    except ValueError:
        return value

    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{formatted}" if negative else formatted


def merge_numeric_fragments(parts: List[str]) -> List[str]:
    merged: List[str] = []
    index = 0

    while index < len(parts):
        current = parts[index]

        if index > 0 and index + 1 < len(parts) and re.fullmatch(r"\d+", current) and re.fullmatch(r",\d+", parts[index + 1]):
            merged.append(f"{current}{parts[index + 1]}")
            index += 2
            continue

        if (
            index > 0
            and index + 1 < len(parts)
            and re.fullmatch(r"\d+", current)
            and re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d+", parts[index + 1])
        ):
            merged.append(f"{current}{parts[index + 1]}")
            index += 2
            continue

        if (
            index + 1 < len(parts)
            and re.fullmatch(r"\d+", current)
            and re.fullmatch(r"\d+\.\d+$", parts[index + 1])
        ):
            merged.append(f"{current}{parts[index + 1]}")
            index += 2
            continue

        merged.append(current)
        index += 1

    return merged


def normalize_numbers_inside_text(value: str) -> str:
    value = normalize_text(value)

    def replacer(match: re.Match[str]) -> str:
        return format_number_two_decimals(match.group(0))

    return re.sub(r"\d[\d\., ]*\d|\d", replacer, value)


def fetch_portal_html() -> str:
    response = requests.get(PORTAL_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def find_pdf_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for anchor in soup.find_all("a", href=True):
        text = normalize_text(anchor.get_text(" ", strip=True))
        if text != TARGET_TITLE:
            continue

        return urljoin(PORTAL_URL, anchor["href"])

    raise RuntimeError(f"Nao encontrei o PDF com o titulo exato: {TARGET_TITLE}")


def fetch_pdf_bytes(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, headers=HEADERS, timeout=60)
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


def slice_annex_lines(lines: List[str]) -> List[str]:
    start_marker = "Tarifas finais - Usuários Cativos"
    end_marker = "(*) Os valores não incluem tributos."

    start_index: Optional[int] = None
    end_index: Optional[int] = None

    for index, line in enumerate(lines):
        if start_index is None and start_marker in line:
            start_index = index
        if start_index is not None and end_marker in line:
            end_index = index
            break

    if start_index is None or end_index is None:
        raise RuntimeError("Nao foi possivel localizar o bloco do ANEXO I com as tarifas.")

    return lines[start_index : end_index + 1]


def split_segments(annex_lines: List[str]) -> Dict[str, List[str]]:
    positions: Dict[str, int] = {}

    for index, line in enumerate(annex_lines):
        if line in SEGMENTS and line not in positions:
            positions[line] = index

    missing = [segment for segment in SEGMENTS if segment not in positions]
    if missing:
        raise RuntimeError(f"Nao foi possivel localizar os segmentos: {', '.join(missing)}")

    ordered_segments = sorted(positions.items(), key=lambda item: item[1])
    sections: Dict[str, List[str]] = {}

    for segment_index, (segment_name, start_index) in enumerate(ordered_segments):
        end_index = len(annex_lines)
        if segment_index + 1 < len(ordered_segments):
            end_index = ordered_segments[segment_index + 1][1]

        section_lines = []
        for line in annex_lines[start_index:end_index]:
            if line.startswith("ars p.es.gov.br"):
                break
            if line.startswith("Av. Nossa Sra."):
                break
            section_lines.append(line)

        sections[segment_name] = section_lines

    return sections


def parse_segment_row(line: str) -> Tuple[str, str, str, str]:
    line = normalize_text(line)
    parts = merge_numeric_fragments(line.split())

    if not parts or not re.fullmatch(r"\d+", parts[0]):
        raise RuntimeError(f"Nao foi possivel interpretar a linha da tabela: {line}")

    classe = parts[0]

    if len(parts) >= 5 and parts[1] == "-":
        return (
            classe,
            normalize_numbers_inside_text(f"- {parts[2]}"),
            format_number_two_decimals(parts[3]),
            normalize_number_text(parts[4]),
        )

    if len(parts) >= 6 and parts[1] == "Acima" and parts[2] == "de":
        return (
            classe,
            normalize_numbers_inside_text(f"Acima de {parts[3]}"),
            format_number_two_decimals(parts[4]),
            normalize_number_text(parts[5]),
        )

    if len(parts) >= 5 and re.fullmatch(r"[\d\.,]+", parts[1]) and re.fullmatch(r"[\d\.,]+", parts[2]):
        return (
            classe,
            normalize_numbers_inside_text(f"{parts[1]} a {parts[2]}"),
            format_number_two_decimals(parts[3]),
            normalize_number_text(parts[4]),
        )

    if len(parts) >= 3:
        return (
            classe,
            normalize_text(" ".join(parts[1:-1])),
            "",
            normalize_number_text(parts[-1]),
        )

    raise RuntimeError(f"Nao foi possivel interpretar a linha da tabela: {line}")


def parse_sections_to_tables(sections: Dict[str, List[str]]) -> List[Dict[str, object]]:
    tables: List[Dict[str, object]] = []

    for segment_name in SEGMENTS:
        rows: List[Dict[str, str]] = []

        for line in sections[segment_name]:
            if line == segment_name:
                continue
            if line.startswith("Classes Volume Mensal"):
                continue
            if line.startswith("(*) Os valores nao incluem tributos"):
                continue
            if not re.match(r"^\d+\s+", line):
                continue

            classe, volume_mensal, valor_fixo, valor_variavel = parse_segment_row(line)
            rows.append(
                {
                    "classe": classe,
                    "volume_mensal_m3": volume_mensal,
                    "valor_fixo_r$": valor_fixo,
                    "valor_variavel_r$_m3": valor_variavel,
                }
            )

        if not rows:
            raise RuntimeError(f"Nenhuma linha foi extraida para o segmento: {segment_name}")

        tables.append({"segmento": segment_name, "dataframe": pd.DataFrame(rows)})

    return tables


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 40)


def save_excel(
    tables: List[Dict[str, object]],
    pdf_url: str,
    output_dir: Path,
) -> Path:
    output_path = output_dir / f"Esgas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        row_pointer = 0
        worksheet_name = "Tarifas"

        for index, table_entry in enumerate(tables, start=1):
            segment_name = str(table_entry["segmento"])
            df = table_entry["dataframe"]

            header_block = pd.DataFrame(
                [[f"Tabela {index}"], [segment_name]],
                columns=["descricao"],
            )
            header_block.to_excel(writer, sheet_name=worksheet_name, index=False, header=False, startrow=row_pointer)
            row_pointer += len(header_block)

            df.to_excel(writer, sheet_name=worksheet_name, index=False, startrow=row_pointer)
            row_pointer += len(df) + 3

        metadata = pd.DataFrame(
            [
                {
                    "titulo_pdf": TARGET_TITLE,
                    "pdf_url": pdf_url,
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
    print("Buscando a pagina de tarifas da ES Gas...")
    html = fetch_portal_html()

    print("Localizando o PDF da decisao solicitada...")
    pdf_url = find_pdf_url(html)
    print(f"PDF selecionado: {pdf_url}")

    print("Lendo PDF em memoria...")
    pdf_bytes = fetch_pdf_bytes(pdf_url)
    lines = extract_pdf_lines(pdf_bytes)

    print("Extraindo o ANEXO I...")
    annex_lines = slice_annex_lines(lines)
    sections = split_segments(annex_lines)
    tables = parse_sections_to_tables(sections)

    output_path = save_excel(tables, pdf_url, Path.cwd())

    print("Concluido.")
    print(f"Tabelas encontradas: {len(tables)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()
