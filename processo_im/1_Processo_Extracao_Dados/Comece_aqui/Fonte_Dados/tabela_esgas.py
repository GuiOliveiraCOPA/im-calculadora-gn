import re
import unicodedata
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
TARGET_TITLE = "Tarifas vigentes - ES Gas"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

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


def normalize_for_match(value: str) -> str:
    value = normalize_text(value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", " ", value)
    return value.lower().strip()


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
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def extract_date_score(text: str) -> int:
    normalized = normalize_for_match(text)
    match = re.search(
        r"(\d{1,2})\s+de\s+("
        r"janeiro|fevereiro|marco|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
        r")\s+de\s+(20\d{2})",
        normalized,
    )
    if not match:
        return 0

    day = int(match.group(1))
    month = MONTHS_PT.get(match.group(2), 0)
    year = int(match.group(3))
    return year * 10000 + month * 100 + day


def score_pdf_candidate(text: str, href: str) -> Optional[int]:
    searchable = normalize_for_match(f"{text} {href}")
    if ".pdf" not in href.lower():
        return None
    if "nota tecnica" in searchable:
        return None
    if "resolucao arsp" not in searchable and "decisao arsp" not in searchable:
        return None
    if "tarif" not in searchable and "reajuste" not in searchable:
        return None

    score = extract_date_score(searchable)
    numbers = [int(value) for value in re.findall(r"\b\d{2,4}\b", searchable)]
    if numbers:
        score += max(numbers)
    if "resolucao arsp" in searchable:
        score += 1_000_000
    if "decisao arsp" in searchable:
        score += 800_000
    if "reajuste tarifario" in searchable:
        score += 50_000
    if "es gas" in searchable:
        score += 10_000
    if "termoeletrico" in searchable:
        score -= 20_000
    return score


def find_pdf_url(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: List[Tuple[int, str, str]] = []

    for anchor in soup.find_all("a", href=True):
        text = normalize_text(anchor.get_text(" ", strip=True))
        href = urljoin(PORTAL_URL, anchor["href"])
        score = score_pdf_candidate(text, href)
        if score is None:
            continue
        candidates.append((score, text, href))

    if not candidates:
        raise RuntimeError("Nao encontrei PDF de resolucao/reajuste tarifario da ES Gas na pagina vigente.")

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, title, href = candidates[0]
    return href, title


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
    start_index: Optional[int] = None
    end_index: Optional[int] = None

    for index, line in enumerate(lines):
        key = normalize_for_match(line)
        if start_index is None and "tarifas" in key and "usuarios cativos" in key:
            start_index = index
        if start_index is not None and "os valores" in key and "incluem tributos" in key:
            end_index = index
            break

    if start_index is None or end_index is None:
        raise RuntimeError("Nao foi possivel localizar o bloco do ANEXO I com as tarifas.")

    return lines[start_index : end_index + 1]


def split_segments(annex_lines: List[str]) -> Dict[str, List[str]]:
    positions: Dict[str, int] = {}
    segment_by_key = {normalize_for_match(segment): segment for segment in SEGMENTS}

    for index, line in enumerate(annex_lines):
        segment_name = segment_by_key.get(normalize_for_match(line))
        if segment_name and segment_name not in positions:
            positions[segment_name] = index

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
    pdf_title: str,
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
                    "titulo_pdf": pdf_title,
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

    print("Localizando o PDF tarifario mais recente...")
    pdf_url, pdf_title = find_pdf_url(html)
    print(f"Titulo selecionado: {pdf_title}")
    print(f"PDF selecionado: {pdf_url}")

    print("Lendo PDF em memoria...")
    pdf_bytes = fetch_pdf_bytes(pdf_url)
    lines = extract_pdf_lines(pdf_bytes)

    print("Extraindo o ANEXO I...")
    annex_lines = slice_annex_lines(lines)
    sections = split_segments(annex_lines)
    tables = parse_sections_to_tables(sections)

    output_path = save_excel(tables, pdf_url, pdf_title, Path.cwd())

    print("Concluido.")
    print(f"Tabelas encontradas: {len(tables)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()
