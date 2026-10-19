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
from pypdf import PdfReader
from bs4 import BeautifulSoup


PORTAL_URL = "https://www.compagas.com.br/portal-de-tarifas/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
CORE_CODES = ["1.1", "1.3", "1.5", "1.6"]
NEW_TABLE_CODES = [
    "1.2", "1.7", "1.8", "1.9", "1.12",
    "2.1", "2.2", "2.3", "2.7", "2.8", "2.9", "2.12",
]
TARGET_CODES = CORE_CODES + [code for code in NEW_TABLE_CODES if code not in CORE_CODES]
LEGACY_TABLE_ALIASES = {
    "1.5": "1.7",
}
TABLE_ROW_LIMITS = {
    "1.1": 9,
    "1.3": 8,
    "1.12": 7,
    "2.1": 9,
    "2.3": 8,
    "2.12": 7,
}



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


def table_spec_like(code: str, source_code: str, title: str) -> TableSpec:
    source = TABLE_SPECS[source_code]
    return TableSpec(
        code=code,
        title=title,
        columns=list(source.columns),
        expected_numeric_tokens=source.expected_numeric_tokens,
        has_currency=source.has_currency,
    )


def cativo_single_row_spec(code: str, title: str) -> TableSpec:
    return TableSpec(
        code=code,
        title=title,
        columns=[
            "tusd_variavel_ec_r$_m3",
            "preco_gas_r$_m3",
            "parcela_conta_grafica_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=5,
        has_currency=False,
    )


def livre_single_row_spec(code: str, title: str) -> TableSpec:
    return TableSpec(
        code=code,
        title=title,
        columns=[
            "tusd_variavel_el_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=3,
        has_currency=False,
    )


def livre_fixed_spec(code: str, title: str) -> TableSpec:
    return TableSpec(
        code=code,
        title=title,
        columns=[
            "faixa_inicial_m3_dia",
            "faixa_final_m3_dia",
            "tusd_fixa_r$",
            "tusd_variavel_el_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=6,
        has_currency=True,
    )


def livre_range_spec(code: str, title: str) -> TableSpec:
    return TableSpec(
        code=code,
        title=title,
        columns=[
            "faixa_inicial_m3_dia",
            "faixa_final_m3_dia",
            "tusd_variavel_el_r$_m3",
            "fator_k_r$_m3",
            "tarifa_r$_m3",
        ],
        expected_numeric_tokens=5,
        has_currency=False,
    )


TABLE_SPECS.update({
    "1.2": cativo_single_row_spec("1.2", "Tabela Segmento Gas Natural Comprimido (GNC)"),
    "1.7": cativo_single_row_spec("1.7", "Tabela Segmento Gas Natural Veicular (GNV)"),
    "1.8": cativo_single_row_spec("1.8", "Tabela Segmento Gas Natural Veicular (GNV) - Transporte Publico"),
    "1.9": cativo_single_row_spec("1.9", "Tabela Segmento Gas Natural Veicular (GNV) - Frotas"),
    "1.12": table_spec_like("1.12", "1.3", "Tabela Segmento Grandes Usuarios QDC acima de 70.000 m3/dia"),
    "2.1": livre_fixed_spec("2.1", "Tabela Segmento Comercial - Mercado Livre"),
    "2.2": livre_single_row_spec("2.2", "Tabela Segmento GNC - Mercado Livre"),
    "2.3": livre_range_spec("2.3", "Tabela Segmento Industrial - Mercado Livre"),
    "2.7": livre_single_row_spec("2.7", "Tabela Segmento GNV - Mercado Livre"),
    "2.8": livre_single_row_spec("2.8", "Tabela Segmento GNV Transporte Publico - Mercado Livre"),
    "2.9": livre_single_row_spec("2.9", "Tabela Segmento GNV Frotas - Mercado Livre"),
    "2.12": livre_range_spec("2.12", "Tabela Segmento Grandes Usuarios - Mercado Livre"),
})


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


def append_pdf_line(lines: List[str], raw_line: str) -> None:
    line = normalize_text(raw_line)
    if not line:
        return
    for part in re.split(r"\s*=\s*=\s*=\s*", line):
        part = re.sub(r"(?<!^)(?=\d+\.\d+\s+Tabela\b)", "\n", part.strip())
        for item in part.splitlines():
            item = item.strip()
            if item:
                lines.append(item)


def pdf_to_lines(pdf_bytes: bytes) -> List[str]:
    lines: List[str] = []

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                append_pdf_line(lines, raw_line)
    except Exception:
        lines = []

    if lines:
        return lines

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw_line in text.splitlines():
                append_pdf_line(lines, raw_line)
    return lines


def slice_table_sections(lines: List[str]) -> Dict[str, List[str]]:
    title_pattern = re.compile(r"^(\d+\.\d+)\s+Tabela\b", re.IGNORECASE)
    start_positions: Dict[str, int] = {}

    for index, line in enumerate(lines):
        match = title_pattern.match(line)
        if not match:
            continue
        code = match.group(1)
        if code in TABLE_SPECS and code not in start_positions:
            start_positions[code] = index

    if not start_positions:
        raise RuntimeError("Nao foi possivel localizar nenhuma tabela alvo no PDF da Compagas.")

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
    line = re.sub(r"(?i)m3(?=\d)", " ", line)
    line = re.sub(r"(?i)mdia(?=\d)", " ", line)
    line = re.sub(r"(\d+,\d{4})(?=\d)", r"\1 ", line)
    tokens = re.findall(r"R\$|\d[\d\.,]*", line)
    return [token.strip() for token in tokens if token.strip()]


def is_row_fragment(line: str) -> bool:
    if re.match(r"^\d", line):
        return True
    if line.startswith("R$ "):
        return True
    return False


def is_single_row_spec(spec: TableSpec) -> bool:
    return not any(column.startswith("faixa_") for column in spec.columns)


def parse_single_row_section(section_lines: List[str], spec: TableSpec) -> pd.DataFrame:
    for line in section_lines:
        tokens = tokenise_numeric_row(line)
        if spec.has_currency:
            tokens = [token for token in tokens if token != "R$"]
        if len(tokens) >= spec.expected_numeric_tokens:
            return pd.DataFrame([tokens[-spec.expected_numeric_tokens:]], columns=spec.columns)
    raise RuntimeError(f"Nenhuma linha valida foi extraida para a tabela {spec.code}.")


def parse_pt_number(value: str) -> Optional[float]:
    try:
        return float(value.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def valid_range_candidate(candidate: List[str], spec: TableSpec) -> bool:
    if len(candidate) != spec.expected_numeric_tokens:
        return False

    numbers = [parse_pt_number(token) for token in candidate]
    if any(number is None for number in numbers):
        return False

    faixa_min = numbers[0]
    faixa_max = numbers[1]
    if faixa_min is None or faixa_max is None or faixa_min < 0 or faixa_max <= faixa_min:
        return False

    components = numbers[3:] if spec.has_currency else numbers[2:]
    if not components:
        return False
    return all(component is not None and 0 <= component <= 100 for component in components)


def parse_range_section(section_lines: List[str], spec: TableSpec) -> pd.DataFrame:
    tokens: List[str] = []
    for line in section_lines:
        if line.startswith('"Notas'):
            break
        tokens.extend(tokenise_numeric_row(line))

    tokens = [token for token in tokens if token != "R$"]
    rows: List[List[str]] = []
    index = 0
    while index <= len(tokens) - spec.expected_numeric_tokens:
        candidate = tokens[index : index + spec.expected_numeric_tokens]
        if valid_range_candidate(candidate, spec):
            rows.append(candidate)
            index += spec.expected_numeric_tokens
        else:
            index += 1

    limit = TABLE_ROW_LIMITS.get(spec.code)
    if limit:
        rows = rows[:limit]

    if not rows:
        raise RuntimeError(f"Nenhuma linha valida foi extraida para a tabela {spec.code}.")

    return pd.DataFrame(rows, columns=spec.columns)


def parse_section_rows(section_lines: List[str], spec: TableSpec) -> pd.DataFrame:
    if is_single_row_spec(spec):
        return parse_single_row_section(section_lines, spec)
    return parse_range_section(section_lines, spec)


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

        written_codes = [code for code in CORE_CODES if code in tables]
        written_codes.extend(code for code in TARGET_CODES if code in tables and code not in written_codes)

        for code in written_codes:
            df = tables[code].copy()
            sheet_name = code.replace(".", "_")[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)

            worksheet = writer.sheets[sheet_name]
            for idx, column in enumerate(df.columns, start=1):
                max_len = max(len(column), *(len(str(value)) for value in df[column].tolist()))
                worksheet.column_dimensions[chr(64 + idx)].width = min(max_len + 2, 25)

    return output_path


def extract_target_tables(pdf_bytes: bytes) -> Dict[str, pd.DataFrame]:
    lines = pdf_to_lines(pdf_bytes)
    sections = slice_table_sections(lines)
    tables: Dict[str, pd.DataFrame] = {}

    for code in TARGET_CODES:
        if code not in sections:
            continue
        spec = TABLE_SPECS[code]
        try:
            tables[code] = parse_section_rows(sections[code], spec)
        except RuntimeError as exc:
            print(f"Aviso: tabela {code} localizada, mas nao foi extraida: {exc}")

    for legacy_code, current_code in LEGACY_TABLE_ALIASES.items():
        if legacy_code not in tables and current_code in tables:
            tables[legacy_code] = tables[current_code].copy()

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


