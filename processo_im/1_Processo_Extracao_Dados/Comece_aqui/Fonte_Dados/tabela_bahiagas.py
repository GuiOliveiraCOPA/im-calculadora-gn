from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
import requests


SITE_URL = "https://www.bahiagas.com.br/tabelatarifaria/"
JSON_URL = "https://www.bahiagas.com.br/tabelatarifaria/tabelacompleta_json.txt"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_tariffs() -> List[Dict[str, object]]:
    response = requests.get(JSON_URL, headers=HEADERS, timeout=60)
    response.raise_for_status()
    return response.json()


def normalize_text(value: object) -> str:
    return str(value or "").replace("\xa0", " ").strip()


def build_blocks(data: List[Dict[str, object]]) -> List[Dict[str, object]]:
    blocks: List[Dict[str, object]] = []
    for entry in data:
        title = normalize_text(entry.get("descricao")) or f"Contrato {entry.get('contrato', '')}"
        vigencia = normalize_text(entry.get("data"))
        rows = []
        for faixa in entry.get("faixa", []):
            rows.append({
                "faixa_min": normalize_text(faixa.get("MIN_FX")),
                "faixa_max": normalize_text(faixa.get("MAX_FX")),
                "tarifa_s_tributos_r$_m3": normalize_text(faixa.get("VAL_ORIGEM")),
                "tarifa_c_tributos_r$_m3": normalize_text(faixa.get("VAL_IMPOSTO")),
            })
        if rows:
            blocks.append({
                "titulo": title,
                "vigencia": vigencia,
                "contrato": normalize_text(entry.get("contrato")),
                "dataframe": pd.DataFrame(rows),
            })
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
    output_path = output_dir / f"Bahiagas_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        worksheet_name = "Tarifas"
        row_pointer = 0
        for block in blocks:
            header = pd.DataFrame(
                [[block["titulo"]], [f"Vigencia: {block['vigencia']} | Contrato: {block['contrato']}"], [""]],
                columns=["descricao"],
            )
            header.to_excel(writer, sheet_name=worksheet_name, index=False, header=False, startrow=row_pointer)
            row_pointer += len(header)
            df = block["dataframe"]
            df.to_excel(writer, sheet_name=worksheet_name, index=False, startrow=row_pointer)
            row_pointer += len(df) + 3

        pd.DataFrame([{
            "site": SITE_URL,
            "json": JSON_URL,
            "extraido_em": datetime.now().isoformat(timespec="seconds"),
            "blocos": len(blocks),
        }]).to_excel(writer, sheet_name="controle", index=False)
        autosize_columns(writer.sheets[worksheet_name])
        autosize_columns(writer.sheets["controle"])
    return output_path


def main() -> None:
    data = fetch_tariffs()
    blocks = build_blocks(data)
    if not blocks:
        raise RuntimeError("Nenhuma tabela tarifaria encontrada no JSON da Bahiagas.")
    output_path = save_excel(blocks, Path.cwd())
    print("Concluido.")
    print(f"Blocos encontrados: {len(blocks)}")
    print(f"Arquivo Excel gerado em: {output_path}")


if __name__ == "__main__":
    main()
