import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup


PORTAL_URL = "https://www.compagas.com.br/portal-de-tarifas/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TARGET_CODES = ["1.1", "1.3", "1.5", "1.6"]


@dataclass
class TableSpec:
    code: str
    title: str
    columns: List[str]
    expected_numeric_tokens: int
    has_currency: bool


TABLE_SPECS: Dict[str, TableSpec] = {
    "1.1": TableSpec(
        code="1.1",
        title="Tabela Segmento Comercial",
        columns=[
            "faixa_inicial_m3_dia",
            "faixa_final_m3_dia",
            "tusd_fixa_r$",
            "tusd_variavel_ec_r$_m3",
            "preco_gas_r$_m3",
            "parcela_conta_grafica_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=8,
        has_currency=True,
    ),
    "1.3": TableSpec(
        code="1.3",
        title="Tabela Segmento Industrial",
        columns=[
            "faixa_inicial_m3_dia",
            "faixa_final_m3_dia",
            "tusd_variavel_ec_r$_m3",
            "preco_gas_r$_m3",
            "parcela_conta_grafica_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=7,
        has_currency=False,
    ),
    "1.6": TableSpec(
        code="1.6",
        title="Tabela Segmento Residencial - Medicao Coletiva",
        columns=[
            "faixa_inicial_m3_dia",
            "faixa_final_m3_dia",
            "tusd_fixa_r$",
            "tusd_variavel_ec_r$_m3",
            "preco_gas_r$_m3",
            "parcela_conta_grafica_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=8,
        has_currency=True,
    ),
    "1.5": TableSpec(
        code="1.5",
        title="Tabela Segmento GNV Postos",
        columns=[
            "faixa_inicial_m3_dia",
            "faixa_final_m3_dia",
            "tusd_fixa_r$",
            "tusd_variavel_ec_r$_m3",
            "preco_gas_r$_m3",
            "parcela_conta_grafica_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=8,
        has_currency=True,
    ),
}


def normalize_text(value: str) -> str:
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.replace("\xa0", " ")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_portal_html() -> str:
    response = requests.get(PORTAL_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def parse_portal_sections(html: str) -> Dict[int, List[Tuple[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    sections: Dict[int, List[Tuple[str, str]]] = {}
    current_year: Optional[int] = None

    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "a"]):
        text = normalize_text(element.get_text(" ", strip=True))
        year_match = re.fullmatch(r"20\d{2}", text)
        if year_match:
            current_year = int(year_match.group(0))
            sections.setdefault(current_year, [])
            continue

        if element.name == "a" and current_year is not None:
            href = element.get("href")
            if not href:
                continue
            absolute_url = urljoin(PORTAL_URL, href)
            if ".pdf" not in absolute_url.lower():
                continue
            sections[current_year].append((text, absolute_url))

    return {year: links for year, links in sections.items() if links}


def extract_resolution_date(text: str) -> Optional[datetime]:
    clean = normalize_text(text).upper()
    patterns = [
        r"(\d{1,2})\s+DE\s+([A-Z]+)\s+DE\s+(20\d{2})",
        r"(\d{1,2})\s+([A-Z]+)\s+(20\d{2})",
        r"(\d{1,2})/(\d{1,2})/(20\d{2})",
    ]
    month_map = {
        "JANEIRO": 1,
        "FEVEREIRO": 2,
        "MARCO": 3,
        "MARÇO": 3,
        "ABRIL": 4,
        "MAIO": 5,
        "JUNHO": 6,
        "JULHO": 7,
        "AGOSTO": 8,
        "SETEMBRO": 9,
        "OUTUBRO": 10,
        "NOVEMBRO": 11,
        "DEZEMBRO": 12,
    }

    for pattern in patterns:
        match = re.search(pattern, clean)
        if not match:
            continue

        if "/" in pattern:
            day, month, year = match.groups()
            return datetime(int(year), int(month), int(day))

        day, month_name, year = match.groups()
        month = month_map.get(month_name)
        if month:
            return datetime(int(year), month, int(day))

    return None


def select_latest_pdf(sections: Dict[int, List[Tuple[str, str]]]) -> Tuple[int, str, str]:
    if not sections:
        raise RuntimeError("Nenhum PDF foi encontrado no portal da Compagas.")

    latest_year = max(sections)
    links = sections[latest_year]

    def rank(item: Tuple[str, str]) -> Tuple[datetime, int]:
        text, _ = item
        parsed_date = extract_resolution_date(text) or datetime(latest_year, 1, 1)
        normalized_text = normalize_text(text).upper()
        resolution_match = re.search(r"RESOLUCAO\s*N[O]?\s*(\d+)", normalized_text)
        resolution_number = int(resolution_match.group(1)) if resolution_match else 0
        return parsed_date, resolution_number

    latest_text, latest_url = max(links, key=rank)
    return latest_year, latest_text, latest_url


def fetch_pdf_bytes(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    return response.content


def pdf_to_lines(pdf_bytes: bytes) -> List[str]:
    lines: List[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                line = normalize_text(raw_line)
                if line:
                    lines.append(line)
    return lines


def slice_table_sections(lines: List[str]) -> Dict[str, List[str]]:
    title_pattern = re.compile(r"^(\d+\.\d+)\s+Tabela\b", re.IGNORECASE)
    start_positions: Dict[str, int] = {}

    for index, line in enumerate(lines):
        match = title_pattern.match(line)
        if match and match.group(1) in TARGET_CODES and match.group(1) not in start_positions:
            start_positions[match.group(1)] = index

    missing = [code for code in TARGET_CODES if code not in start_positions]
    if missing:
        raise RuntimeError(f"Nao foi possivel localizar os titulos das tabelas: {', '.join(missing)}")

    ordered = sorted(start_positions.items(), key=lambda item: item[1])
    sections: Dict[str, List[str]] = {}

    for position, (code, start_index) in enumerate(ordered):
        end_index = len(lines)
        if position + 1 < len(ordered):
            end_index = ordered[position + 1][1]

        chunk = lines[start_index:end_index]
        trimmed: List[str] = []
        for line in chunk:
            if line.startswith("Nota do Faturamento"):
                break
            trimmed.append(line)

        sections[code] = trimmed

    return sections


def tokenise_numeric_row(line: str) -> List[str]:
    tokens = re.findall(r"R\$|\d[\d\.,]*", line)
    return [token.strip() for token in tokens if token.strip()]


def is_row_fragment(line: str) -> bool:
    if re.match(r"^\d", line):
        return True
    if line.startswith("R$ "):
        return True
    return False


def parse_section_rows(section_lines: List[str], spec: TableSpec) -> pd.DataFrame:
    rows: List[List[str]] = []
    buffer_tokens: List[str] = []
    started = False

    for line in section_lines[1:]:
        if line.startswith('"Notas'):
            break

        if not started:
            if is_row_fragment(line):
                started = True
            else:
                continue

        if not is_row_fragment(line):
            if buffer_tokens:
                parsed = finalize_row(buffer_tokens, spec)
                if parsed:
                    rows.append(parsed)
                buffer_tokens = []
            continue

        buffer_tokens.extend(tokenise_numeric_row(line))
        parsed = finalize_row(buffer_tokens, spec)
        if parsed:
            rows.append(parsed)
            buffer_tokens = []

    if buffer_tokens:
        parsed = finalize_row(buffer_tokens, spec)
        if parsed:
            rows.append(parsed)

    if not rows:
        raise RuntimeError(f"Nenhuma linha valida foi extraida para a tabela {spec.code}.")

    return pd.DataFrame(rows, columns=spec.columns)


def finalize_row(tokens: List[str], spec: TableSpec) -> Optional[List[str]]:
    filtered = list(tokens)
    if spec.has_currency:
        if "R$" not in filtered:
            return None
        filtered = [token for token in filtered if token != "R$"]

    if len(filtered) < spec.expected_numeric_tokens:
        return None

    candidate = filtered[: spec.expected_numeric_tokens]
    return candidate


def build_excel(
    tables: Dict[str, pd.DataFrame],
    output_dir: Path,
    year: int,
    resolution_text: str,
    pdf_url: str,
) -> Path:
    output_path = output_dir / f"Compagas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    metadata = pd.DataFrame(
        [
            {
                "ano_portal": year,
                "resolucao": resolution_text,
                "pdf_url": pdf_url,
                "extraido_em": datetime.now().isoformat(timespec="seconds"),
            }
        ]
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        metadata.to_excel(writer, sheet_name="controle", index=False)

        for code in TARGET_CODES:
            df = tables[code].copy()
            df.to_excel(writer, sheet_name=code.replace(".", "_"), index=False)

            worksheet = writer.sheets[code.replace(".", "_")]
            for idx, column in enumerate(df.columns, start=1):
                max_len = max(len(column), *(len(str(value)) for value in df[column].tolist()))
                worksheet.column_dimensions[chr(64 + idx)].width = min(max_len + 2, 25)

    return output_path


def extract_target_tables(pdf_bytes: bytes) -> Dict[str, pd.DataFrame]:
    lines = pdf_to_lines(pdf_bytes)
    sections = slice_table_sections(lines)
    tables: Dict[str, pd.DataFrame] = {}

    for code in TARGET_CODES:
        spec = TABLE_SPECS[code]
        tables[code] = parse_section_rows(sections[code], spec)

    return tables


def main() -> None:
    print("Buscando o PDF mais recente no portal...")
    html = fetch_portal_html()
    sections = parse_portal_sections(html)
    year, resolution_text, pdf_url = select_latest_pdf(sections)

    print(f"Ano mais recente: {year}")
    print(f"Resolucao mais recente: {resolution_text}")
    print(f"PDF selecionado: {pdf_url}")

    print("Lendo PDF em memoria...")
    pdf_bytes = fetch_pdf_bytes(pdf_url)

    print("Extraindo tabelas alvo...")
    tables = extract_target_tables(pdf_bytes)

    output_dir = Path.cwd()
    excel_path = build_excel(tables, output_dir, year, resolution_text, pdf_url)

    print("Concluido.")
    print(f"Arquivo Excel gerado em: {excel_path}")


if __name__ == "__main__":
    main()
