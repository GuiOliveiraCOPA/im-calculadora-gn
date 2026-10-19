import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import fitz
import pandas as pd
import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "Mozilla/5.0"}
COMGAS_PAGE = "https://www.comgas.com.br/sobre-sua-conta/tarifas"
NATURGY_SP_PAGE = "https://www.naturgy.com.br/atendimento/tarifas/tarifa_sao_paulo"
ARSESP_PAGE = "https://www.arsesp.sp.gov.br/Paginas/Tarifas.aspx#gascanalizado"
NATURGY_RJ_PAGE = "https://www.naturgy.com.br/atendimento/tarifas/tarifa_rio_de_janeiro/"
MAX_RANGE = Decimal("99999999999")
THREE_DECIMALS = Decimal("0.001")
TWO_DECIMALS = Decimal("0.01")


OUTPUT_COLUMNS = [
    "Segmento Copa",
    "Concessionaria",
    "Segmento",
    "Faixa Mín (m3)",
    "Faixa Máx (m3)",
    "Tarifa (R$/m³)",
    "Termo Fixo (R$)",
]


def http_get(url: str, timeout: int = 120) -> requests.Response:
    session = requests.Session()
    session.trust_env = False
    response = session.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_deliberation_number(text: str) -> int:
    match = re.search(r"(\d{3,5})", normalize_text(text))
    return int(match.group(1)) if match else -1


def fetch_pdf_bytes(url: str) -> bytes:
    return http_get(url).content


def pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def parse_brazilian_decimal(value: str) -> Decimal:
    cleaned = str(value).strip().replace(" ", "")
    cleaned = cleaned.replace(".", "").replace(",", ".")
    return Decimal(cleaned)


def format_us_number(value: Decimal, decimals: Decimal) -> str:
    quantized = value.quantize(decimals, rounding=ROUND_HALF_UP)
    places = abs(decimals.as_tuple().exponent)
    return f"{quantized:,.{places}f}"


def format_m3(value: Decimal) -> str:
    return format_us_number(value, THREE_DECIMALS)


def format_currency(value: Decimal, dash_for_zero: bool = False) -> str:
    quantized = value.quantize(TWO_DECIMALS, rounding=ROUND_HALF_UP)
    if dash_for_zero and quantized == Decimal("0.00"):
        return "R$ -"
    prefix = "-R$ " if quantized < 0 else "R$ "
    return prefix + format_us_number(abs(quantized), TWO_DECIMALS)


def split_volume_range(volume_text: str) -> Tuple[Decimal, Decimal]:
    normalized = normalize_spaces(normalize_text(volume_text)).lower()
    normalized = normalized.replace("m3", "").strip()
    if normalized.startswith("faixa unica") or normalized == "unico":
        return Decimal("0"), MAX_RANGE
    if " a " in normalized:
        left, right = [part.strip() for part in normalized.split(" a ", 1)]
        return parse_brazilian_decimal(left), parse_brazilian_decimal(right)
    if re.fullmatch(r"\d[\d\.]*\s*-\s*\d[\d\.]*", normalized):
        left, right = [part.strip() for part in normalized.split("-", 1)]
        return parse_brazilian_decimal(left), parse_brazilian_decimal(right)
    if normalized.startswith(">"):
        base = parse_brazilian_decimal(normalized.replace(">", "", 1).strip())
        return base + Decimal("0.01"), MAX_RANGE
    if normalized.startswith("acima de"):
        base = parse_brazilian_decimal(normalized.replace("acima de", "", 1).strip())
        return base + Decimal("0.01"), MAX_RANGE
    raise RuntimeError(f"Faixa de consumo nao reconhecida: {volume_text}")


def select_comgas_pdf_url() -> str:
    soup = BeautifulSoup(http_get(COMGAS_PAGE, timeout=60).text, "html.parser")
    candidates: List[Tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        text = normalize_spaces(anchor.get_text(" ", strip=True))
        href = urljoin(COMGAS_PAGE, anchor["href"])
        if ".pdf" not in href.lower():
            continue
        score = extract_deliberation_number(text + " " + href)
        if "vigente" in normalize_text(text).lower():
            score += 100000
        candidates.append((score, href))
    if not candidates:
        raise RuntimeError("Nao foi possivel localizar o PDF atual da Comgas.")
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def select_naturgy_sp_urls() -> Dict[str, str]:
    soup = BeautifulSoup(http_get(NATURGY_SP_PAGE, timeout=60).text, "html.parser")
    urls: Dict[str, str] = {}
    best_full = (-1, "")
    best_compact = (-1, "")
    for anchor in soup.find_all("a", href=True):
        text = normalize_spaces(anchor.get_text(" ", strip=True))
        href = urljoin(NATURGY_SP_PAGE, anchor["href"])
        if ".pdf" not in href.lower():
            continue
        normalized = normalize_text(text).lower()
        score = extract_deliberation_number(text + " " + href)
        if "vigentes na integra" in normalized and score > best_full[0]:
            best_full = (score, href)
        if "modo compacto" in normalized and score > best_compact[0]:
            best_compact = (score, href)
    if not best_full[1] or not best_compact[1]:
        raise RuntimeError("Nao foi possivel localizar os PDFs atuais da Naturgy SP.")
    return {"full": best_full[1], "compact": best_compact[1]}


def is_arsesp_pdf_for_utility(pdf_bytes: bytes, utility_keyword: str) -> bool:
    text = normalize_text(pdf_text_from_bytes(pdf_bytes)).upper()
    return "DISTRIBUICAO DE GAS CANALIZADO" in text and utility_keyword in text


def select_arsesp_necta_pdf_url() -> str:
    soup = BeautifulSoup(http_get(ARSESP_PAGE, timeout=60).text, "html.parser")
    candidates: List[Tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        text = normalize_spaces(anchor.get_text(" ", strip=True))
        href = urljoin(ARSESP_PAGE, anchor["href"])
        if ".pdf" not in href.lower():
            continue
        if "deliberacao arsesp" not in normalize_text(text).lower():
            continue
        score = extract_deliberation_number(text + " " + href)
        candidates.append((score, href))
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, href in candidates:
        pdf_bytes = fetch_pdf_bytes(href)
        if is_arsesp_pdf_for_utility(pdf_bytes, "NECTA"):
            return href
    raise RuntimeError("Nao foi possivel localizar o PDF atual da NECTA na ARSESP.")


def select_rio_pdf_urls() -> Dict[str, str]:
    soup = BeautifulSoup(http_get(NATURGY_RJ_PAGE, timeout=60).text, "html.parser")
    urls: Dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        text = normalize_spaces(anchor.get_text(" ", strip=True))
        href = urljoin(NATURGY_RJ_PAGE, anchor["href"])
        if ".pdf" not in href.lower():
            continue
        if text.startswith("Tarifas da CEG RIO") and "cegrio" not in urls:
            urls["cegrio"] = href
        elif text.startswith("Tarifas da CEG") and "ceg" not in urls:
            urls["ceg"] = href
    if "ceg" not in urls or "cegrio" not in urls:
        raise RuntimeError("Nao foi possivel localizar os PDFs atuais do RJ.")
    return urls


def extract_segment_block(normalized_pdf_text: str, title_pattern: str) -> str:
    match = re.search(title_pattern, normalized_pdf_text)
    if not match:
        raise RuntimeError(f"Segmento nao encontrado: {title_pattern}")
    start = match.start()
    ends = [
        normalized_pdf_text.find("Nota do Faturamento", start),
        normalized_pdf_text.find("Notas:", start),
    ]
    ends = [value for value in ends if value != -1]
    end = min(ends) if ends else len(normalized_pdf_text)
    return normalized_pdf_text[start:end]


def clean_block_lines(block_text: str) -> List[str]:
    lines: List[str] = []
    for raw_line in block_text.splitlines():
        line = normalize_spaces(raw_line)
        if not line:
            continue
        if line.startswith("SEGMENTO ") or line.startswith("ANEXO ") or line.startswith("AREA DE CONCESSAO"):
            continue
        if any(marker in line for marker in [
            "Classe",
            "Volume (m3/mes)",
            "Termo Fixo",
            "Termo Variavel",
            "Pagina ",
            "Este documento pode",
        ]):
            continue
        lines.append(line)
    return lines


def parse_sp_segment_rows(block_text: str) -> List[Dict[str, str]]:
    lines = clean_block_lines(block_text)
    chunks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in lines:
        if re.fullmatch(r"\d+", line):
            if current:
                chunks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        chunks.append(current)

    rows: List[Dict[str, str]] = []
    number_pattern = re.compile(r"-?[\d\.,]+")
    for chunk in chunks:
        body = " ".join(chunk[1:])
        matches = list(number_pattern.finditer(body))
        if len(matches) < 2:
            continue
        fixed_value = matches[-2].group(0)
        variable_value = matches[-1].group(0)
        volume = normalize_spaces(body[: matches[-2].start()]).replace("Faixa Unica", "Faixa unica")
        rows.append({
            "faixa_consumo_m3_mes": volume,
            "termo_fixo": fixed_value,
            "tarifa": variable_value,
        })
    return rows


def build_output_row(segmento_copa: str, concessionaria: str, segmento: str, faixa_texto: str, tarifa_texto: str, termo_fixo_texto: str) -> Dict[str, str]:
    faixa_min, faixa_max = split_volume_range(faixa_texto)
    return {
        "Segmento Copa": segmento_copa,
        "Concessionaria": concessionaria,
        "Segmento": segmento,
        "Faixa Mín (m3)": format_m3(faixa_min),
        "Faixa Máx (m3)": format_m3(faixa_max),
        "Tarifa (R$/m³)": format_currency(parse_brazilian_decimal(tarifa_texto), dash_for_zero=True),
        "Termo Fixo (R$)": format_currency(parse_brazilian_decimal(termo_fixo_texto)),
    }


def extract_sp_rows_for_source(pdf_bytes: bytes, segment_specs: List[Tuple[str, str, str, str]], concessionaria: str) -> List[Dict[str, str]]:
    normalized_pdf_text = normalize_text(pdf_text_from_bytes(pdf_bytes))
    rows: List[Dict[str, str]] = []
    for segmento_copa, segmento, _, pattern in segment_specs:
        block_text = extract_segment_block(normalized_pdf_text, pattern)
        parsed_rows = parse_sp_segment_rows(block_text)
        for row in parsed_rows:
            rows.append(build_output_row(segmento_copa, concessionaria, segmento, row["faixa_consumo_m3_mes"], row["tarifa"], row["termo_fixo"]))
    return rows


def is_rj_range_line(line: str) -> bool:
    normalized = normalize_spaces(normalize_text(line)).lower()
    return bool(
        re.fullmatch(r"\d[\d\.]*\s*-\s*\d[\d\.]*", normalized)
        or re.fullmatch(r"acima de\s+\d[\d\.]*", normalized)
        or normalized.startswith("faixa unica")
    )


def is_rj_tariff_line(line: str) -> bool:
    return bool(re.fullmatch(r"\d+,\d+", normalize_spaces(line)))


def extract_rj_pairs(pdf_bytes: bytes) -> List[Tuple[str, str]]:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = doc.load_page(0).get_text()
    lines = [normalize_spaces(line) for line in text.splitlines() if normalize_spaces(line)]
    pairs: List[Tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if normalize_spaces(normalize_text(line)).lower().startswith("onde:"):
            break
        if is_rj_range_line(line):
            j = i + 1
            while j < len(lines):
                candidate = lines[j]
                normalized_candidate = normalize_spaces(normalize_text(candidate)).lower()
                if normalized_candidate.startswith("onde:"):
                    i = len(lines)
                    break
                if is_rj_tariff_line(candidate):
                    pairs.append((line, candidate))
                    i = j
                    break
                j += 1
        i += 1
    return pairs


def build_rj_rows(pairs: List[Tuple[str, str]], concessionaria: str) -> List[Dict[str, str]]:
    segment_map = [
        ("CONDOMINIOS", "Residencial", 0, 4),
        ("COMERCIAL E SERVIÇOS", "Comercial e Outros", 8, 14),
        ("INDUSTRIAL", "Industrial", 44, 54),
    ]
    rows: List[Dict[str, str]] = []
    for segmento_copa, segmento, start, end in segment_map:
        for faixa_texto, tarifa_texto in pairs[start:end]:
            rows.append(build_output_row(segmento_copa, concessionaria, segmento, faixa_texto, tarifa_texto, "0,00"))
    return rows


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def write_grouped_dataframe(writer, df: pd.DataFrame, sheet_name: str, group_column: str) -> None:
    row_pointer = 0
    for group_name in df[group_column].drop_duplicates():
        group_df = df[df[group_column] == group_name].copy()
        title = pd.DataFrame([[str(group_name)]], columns=[df.columns[0]])
        title.to_excel(writer, sheet_name=sheet_name, index=False, header=False, startrow=row_pointer)
        row_pointer += 2
        group_df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row_pointer)
        row_pointer += len(group_df) + 3


def save_excel(df: pd.DataFrame, control_rows: List[Dict[str, str]], output_dir: Path) -> Path:
    output_path = output_dir / f"Sp_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        write_grouped_dataframe(writer, df, "SP", "Concessionaria")
        pd.DataFrame(control_rows).to_excel(writer, sheet_name="controle", index=False)
        for sheet_name in ["SP", "controle"]:
            autosize_columns(writer.sheets[sheet_name])
    return output_path


def extract_sp_dataframe() -> Tuple[pd.DataFrame, List[Dict[str, str]]]:
    print("Localizando PDFs atuais de SP...")
    comgas_pdf_url = select_comgas_pdf_url()
    naturgy_sp_urls = select_naturgy_sp_urls()
    necta_pdf_url = select_arsesp_necta_pdf_url()

    print("Baixando fontes de SP...")
    comgas_pdf = fetch_pdf_bytes(comgas_pdf_url)
    naturgy_full_pdf = fetch_pdf_bytes(naturgy_sp_urls["full"])
    necta_pdf = fetch_pdf_bytes(necta_pdf_url)

    print("Extraindo SP...")
    sp_rows: List[Dict[str, str]] = []
    sp_rows.extend(extract_sp_rows_for_source(
        comgas_pdf,
        [
            ("CONDOMINIOS", "Residencial - Medição Coletiva", "", r"SEGMENTO RESIDENCIAL\s*-?\s*MEDICAO COLETIVA"),
            ("COMERCIAL E SERVIÇOS", "Comercial", "", r"SEGMENTO COMERCIAL(?!\s*-?\s*AQUECIMENTO)"),
            ("INDUSTRIAL", "Industrial e Interruptível", "", r"SEGMENTO INDUSTRIAL E INTERRUPTIVEL"),
            ("REVENDA", "Residencial", "", r"SEGMENTO RESIDENCIAL(?!\s*-?\s*MEDICAO|\s*-?\s*AQUECIMENTO)"),
        ],
        "SP (Comgás)",
    ))
    sp_rows.extend(extract_sp_rows_for_source(
        naturgy_full_pdf,
        [
            ("REVENDA", "Residencial", "", r"SEGMENTO RESIDENCIAL(?!\s*-?\s*MEDICAO)"),
            ("CONDOMINIOS", "Residencial - Medição Coletiva", "", r"SEGMENTO RESIDENCIAL\s*-?\s*MEDICAO COLETIVA"),
            ("COMERCIAL E SERVIÇOS", "Comercial", "", r"SEGMENTO COMERCIAL(?!\s*-?\s*AQUECIMENTO)"),
            ("INDUSTRIAL", "Industrial", "", r"SEGMENTO INDUSTRIAL(?!\s+E)"),
        ],
        "SP (Naturgy)",
    ))
    sp_rows.extend(extract_sp_rows_for_source(
        necta_pdf,
        [
            ("REVENDA", "Residencial", "", r"SEGMENTO RESIDENCIAL(?!\s*-?\s*MEDICAO|\s*-?\s*AQUECIMENTO)"),
            ("CONDOMINIOS", "Residencial - Medição Coletiva", "", r"SEGMENTO RESIDENCIAL\s*-?\s*MEDICAO COLETIVA"),
            ("COMERCIAL E SERVIÇOS", "Comercial", "", r"SEGMENTO COMERCIAL(?!\s*-?\s*AQUECIMENTO)"),
            ("INDUSTRIAL", "Industrial e Interruptível", "", r"SEGMENTO INDUSTRIAL/INTERRUPTIVEL"),
        ],
        "SP (Necta)",
    ))

    sp_df = pd.DataFrame(sp_rows, columns=OUTPUT_COLUMNS)
    control_rows = [
        {"fonte": "Comgás SP", "pagina": COMGAS_PAGE, "pdf": comgas_pdf_url},
        {"fonte": "Naturgy SP", "pagina": NATURGY_SP_PAGE, "pdf": naturgy_sp_urls["full"]},
        {"fonte": "NECTA SP", "pagina": ARSESP_PAGE, "pdf": necta_pdf_url},
    ]
    return sp_df, control_rows


def main() -> None:
    sp_df, control_rows = extract_sp_dataframe()
    output_path = save_excel(sp_df, control_rows, Path.cwd())
    print("Concluido.")
    print(f"Linhas SP: {len(sp_df)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()


