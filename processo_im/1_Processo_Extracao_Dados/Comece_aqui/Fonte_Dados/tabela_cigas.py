import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup


SITE_URL = "https://www.cigas.com.br/tabela-tarifaria"
HEADERS = {"User-Agent": "Mozilla/5.0"}
DATA_HOJE = datetime.now().strftime("%Y-%m-%d")
ARQUIVO_BASE = f"Cigas_{DATA_HOJE}"

TITULOS_COM_FAIXA = {
    "INDUSTRIAL",
    "MATÉRIA-PRIMA",
    "MATERIA-PRIMA",
    "INDUSTRIAL: COGERAÇÃO, CLIMATIZAÇÃO E GERAÇÃO PRÓPRIA DE ENERGIA",
    "INDUSTRIAL: COGERACAO, CLIMATIZACAO E GERACAO PROPRIA DE ENERGIA",
    "COMERCIAL E INDUSTRIAL BAIXO CONSUMO*",
    "COMERCIAL: COGERAÇÃO, CLIMATIZAÇÃO E GERAÇÃO PRÓPRIA DE ENERGIA",
    "COMERCIAL: COGERACAO, CLIMATIZACAO E GERACAO PROPRIA DE ENERGIA",
}
TITULOS_VALOR_UNICO = {
    "GÁS NATURAL VEÍCULAR - GNV",
    "GAS NATURAL VEICULAR - GNV",
    "GÁS NATURAL COMPRIMIDO, HIDROVIÁRIO e LIQUEFEITO (GNC/GNH e GNL)",
    "GAS NATURAL COMPRIMIDO, HIDROVIARIO e LIQUEFEITO (GNC/GNH e GNL)",
    "TERMELÉTRICO",
    "TERMELETRICO",
}


def limpar(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "").strip())


def normalizar(texto: str) -> str:
    mapa = str.maketrans("ÁÀÃÂÉÊÍÓÔÕÚÇáàãâéêíóôõúç", "AAAAEEIOOOUCaaaaeeiooouc")
    return limpar(texto).translate(mapa).upper()


def buscar_pdfs_vigentes() -> dict:
    html = requests.get(SITE_URL, headers=HEADERS, timeout=60).text
    soup = BeautifulSoup(html, "html.parser")
    pdfs = {}
    for link in soup.find_all("a", href=True):
        texto = limpar(link.get_text(" "))
        href = link["href"]
        if ".pdf" not in href.lower():
            continue
        url = urljoin(SITE_URL, href)
        chave = normalizar(texto + " " + href)
        if "TUSD" in chave:
            pdfs["TUSD"] = url
        elif "TOM" in chave:
            pdfs["TOM"] = url
    if "TUSD" not in pdfs:
        pdfs["TUSD"] = "https://www.cigas.com.br/_files/ugd/82de1a_2006bf5af0584bceb9c08f99572cca21.pdf"
    if "TOM" not in pdfs:
        pdfs["TOM"] = "https://www.cigas.com.br/_files/ugd/82de1a_4b43fd09e81341f5ab52e3e7a2be095d.pdf"
    return pdfs


def linhas_pdf(url: str) -> list[str]:
    conteudo = requests.get(url, headers=HEADERS, timeout=120).content
    linhas = []
    with pdfplumber.open(BytesIO(conteudo)) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            for linha in texto.splitlines():
                linha = limpar(linha)
                if linha:
                    linhas.append(linha)
    return linhas


def numero_br_para_float(valor: str) -> float:
    return float(valor.replace(".", "").replace(",", "."))


def formatar_numero(valor: float) -> str:
    if abs(valor - round(valor)) < 0.000001:
        return f"{int(round(valor)):,}".replace(",", ".")
    return f"{valor:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")


def converter_faixa(valor: str, diario: bool) -> str:
    if not diario or valor.lower().startswith("acima"):
        return valor
    return formatar_numero(numero_br_para_float(valor) * 30)


def extrair_tusd(linhas: list[str]) -> list[list[str]]:
    rows = []
    titulo = None
    diario = False

    for linha in linhas:
        chave = normalizar(linha)
        if chave in {normalizar(t) for t in TITULOS_COM_FAIXA}:
            titulo = linha.replace("*", "").strip()
            diario = chave in {
                "INDUSTRIAL",
                "MATERIA-PRIMA",
                "INDUSTRIAL: COGERACAO, CLIMATIZACAO E GERACAO PROPRIA DE ENERGIA",
            }
            rows.append([titulo, "", "", ""])
            rows.append(["faixa_min_m3_mes", "faixa_max_m3_mes", "tarifa_tusd_ex_tributos_r$_m3", "observacao"])
            continue

        if chave in {normalizar(t) for t in TITULOS_VALOR_UNICO}:
            titulo = linha.strip()
            rows.append([titulo, "", "", ""])
            rows.append(["tipo", "tarifa_tusd_ex_tributos_r$_m3", "", ""])
            continue

        if not rows:
            continue

        match = re.match(r"^(\d[\d.]*)\s+(\d[\d.]*)\s+(\d+,\d{4})$", linha)
        if match and titulo:
            minimo, maximo, tarifa = match.groups()
            rows.append([converter_faixa(minimo, diario), converter_faixa(maximo, diario), tarifa, "faixa diária convertida para mês" if diario else ""])
            continue

        match = re.match(r"^Acima de\s+(\d[\d.]*)\s+(\d+,\d{4})$", linha, flags=re.IGNORECASE)
        if match and titulo:
            minimo, tarifa = match.groups()
            minimo = converter_faixa(minimo, diario)
            rows.append([minimo, "Acima", tarifa, "faixa diária convertida para mês" if diario else ""])
            continue

        match = re.match(r"^(\d+,\d{4})$", linha)
        if match and rows and rows[-1][0] == "tipo":
            rows.append(["Faixa única", match.group(1), "", ""])

    return rows


def extrair_tom(linhas: list[str]) -> list[list[str]]:
    rows = [["Tarifa de Operação e Manutenção - TOM", "", "", ""], ["tipo", "tarifa_tom_ex_tributos_r$_m3", "", ""]]
    for linha in linhas:
        match = re.match(r"^(\d+,\d{4})$", linha)
        if match:
            rows.append(["Faixa única", match.group(1), "", ""])
            break
    return rows


def salvar_excel(rows: list[list[str]], controle: dict) -> Path:
    output = Path.cwd() / f"{ARQUIVO_BASE}.xlsx"
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="Tarifas", index=False, header=False)
        pd.DataFrame([controle]).to_excel(writer, sheet_name="controle", index=False)
        for sheet in writer.sheets.values():
            for col in sheet.columns:
                letter = col[0].column_letter
                width = max(12, min(60, max(len(str(cell.value or "")) for cell in col) + 2))
                sheet.column_dimensions[letter].width = width
    return output


def main() -> None:
    pdfs = buscar_pdfs_vigentes()
    linhas_tusd = linhas_pdf(pdfs["TUSD"])
    linhas_tom = linhas_pdf(pdfs["TOM"])
    rows = extrair_tusd(linhas_tusd)
    rows.append(["", "", "", ""])
    rows.extend(extrair_tom(linhas_tom))
    output = salvar_excel(rows, {"site": SITE_URL, "pdf_tusd": pdfs["TUSD"], "pdf_tom": pdfs["TOM"], "extraido_em": datetime.now().isoformat(timespec="seconds")})
    print("Concluido.")
    print(f"Arquivo Excel gerado em: {output}")


if __name__ == "__main__":
    main()