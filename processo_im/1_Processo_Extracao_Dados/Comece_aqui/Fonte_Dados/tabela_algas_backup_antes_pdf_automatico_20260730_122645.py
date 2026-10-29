import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import pdfplumber
import requests


SITE_URL = "https://www.arsal.al.gov.br/tarifas-mercado-cativo1/category/362-estrutura-tarifaria"
PDF_URL = "https://www.arsal.al.gov.br/tarifas-mercado-cativo1?task=download.send&id=1363&catid=362&m=0"
HEADERS = {"User-Agent": "Mozilla/5.0"}
OUTPUT_COLUMNS = ["faixa_consumo_m3_mes", "tarifa_ex_tributos_r$_m3"]


TITLE_ALIASES = {
    "TARIFA RESIDENCIAL": "Residencial",
    "TARIFA COMERCIAL": "Comercial",
    "TARIFA INDUSTRIAL": "Industrial",
    "TARIFA COGERAÇÃO/GERAÇÃO/CLIMATIZAÇÃO": "Cogeração/Geração/Climatização",
    "TARIFA COGERACAO/GERACAO/CLIMATIZACAO": "Cogeração/Geração/Climatização",
    "TARIFA GÁS": "Gás",
    "TARIFA GAS": "Gás",
}


def download_pdf() -> bytes:
    response = requests.get(PDF_URL, headers=HEADERS, timeout=120)
    response.raise_for_status()
    return response.content


def extract_lines(pdf_bytes: bytes) -> List[str]:
    lines: List[str] = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                cleaned = re.sub(r"\s+", " ", line).strip()
                if cleaned:
                    lines.append(cleaned)
    return lines


def normalize_title(line: str) -> str:
    return line.upper().replace("Á", "A").replace("Ã", "A").replace("Ç", "C").replace("É", "E")


def parse_br_number(value: str) -> float:
    return float(value.replace(".", "").replace(",", "."))


def format_br_number(value: float) -> str:
    rounded = round(value)
    return f"{rounded:,}".replace(",", ".")


def convert_range_to_monthly(range_text: str, daily: bool) -> str:
    text = range_text.strip()
    if not daily:
        return text
    if text.lower() in {"unica", "única"}:
        return "Única"

    def repl(match) -> str:
        return format_br_number(parse_br_number(match.group(0)) * 30)

    converted = re.sub(r"\d[\d\.]*", repl, text)
    return converted


def parse_tariff_blocks(lines: List[str]) -> Tuple[List[Dict[str, object]], str]:
    blocks: List[Dict[str, object]] = []
    current: Dict[str, object] | None = None
    daily = False
    vigency = ""

    for line in lines:
        if "Em vigor" in line or "Homologada" in line:
            vigency = f"{vigency} {line}".strip()
            continue

        normalized = normalize_title(line)
        if normalized in {normalize_title(title) for title in TITLE_ALIASES}:
            if current and current["rows"]:
                blocks.append(current)
            original_key = next(title for title in TITLE_ALIASES if normalize_title(title) == normalized)
            current = {"titulo": TITLE_ALIASES[original_key], "rows": []}
            daily = False
            continue

        if current is None:
            continue

        if "Faixas" in line and ("dia" in line.lower() or "/dia" in line.lower()):
            daily = True
            continue
        if "Faixas" in line and ("mês" in line.lower() or "mes" in line.lower()):
            daily = False
            continue
        if "Tarifa Ex-Tributos" in line or "ARSAL" in line or "Rua Engenheiro" in line or "Telefone:" in line:
            continue

        match = re.match(r"(.+?)\s+(\d+,\d{4})$", line)
        if not match:
            continue

        range_text, tariff = match.groups()
        current["rows"].append({
            "faixa_consumo_m3_mes": convert_range_to_monthly(range_text, daily),
            "tarifa_ex_tributos_r$_m3": tariff,
        })

    if current and current["rows"]:
        blocks.append(current)

    if not blocks:
        raise RuntimeError("Nenhuma tabela tarifaria encontrada no PDF da ARSAL/Algas.")

    return blocks, vigency


def autosize_columns(worksheet) -> None:
    for column_cells in worksheet.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        worksheet.column_dimensions[letter].width = min(max_length + 2, 45)


def save_excel(blocks: List[Dict[str, object]], vigency: str, output_dir: Path) -> Path:
    output_path = output_dir / f"Algas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        sheet_name = "Tarifas"
        row_pointer = 0
        for block in blocks:
            pd.DataFrame([[block["titulo"]]], columns=["descricao"]).to_excel(
                writer,
                sheet_name=sheet_name,
                index=False,
                header=False,
                startrow=row_pointer,
            )
            row_pointer += 1
            df = pd.DataFrame(block["rows"], columns=OUTPUT_COLUMNS)
            df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=row_pointer)
            row_pointer += len(df) + 2

        pd.DataFrame([{
            "site": SITE_URL,
            "pdf": PDF_URL,
            "vigencia": vigency,
            "extraido_em": datetime.now().isoformat(timespec="seconds"),
            "observacao": "Faixas em m3/dia convertidas para m3/mes multiplicando por 30.",
        }]).to_excel(writer, sheet_name="controle", index=False)
        autosize_columns(writer.sheets[sheet_name])
        autosize_columns(writer.sheets["controle"])
    return output_path


def main() -> None:
    pdf_bytes = download_pdf()
    lines = extract_lines(pdf_bytes)
    blocks, vigency = parse_tariff_blocks(lines)
    output_path = save_excel(blocks, vigency, Path.cwd())
    print("Concluido.")
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()

