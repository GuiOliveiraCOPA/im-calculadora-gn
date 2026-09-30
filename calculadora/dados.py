"""Carga e validação da base tarifária (data/tarifas.json)."""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path

CAMPOS_TEXTO = ("uf", "segmento_copa", "concessionaria", "segmento", "preco_concessionaria")
CAMPOS_NUMERICOS = ("faixa_min", "faixa_max", "tarifa", "termo_fixo", "pis_cofins", "icms", "ordem")


class TarifasInvalidas(Exception):
    """A base tarifária não pode ser usada pela calculadora."""


@dataclass(frozen=True)
class BaseTarifaria:
    records: tuple[dict, ...]
    generated_at: str
    source: str


def _numero_valido(valor) -> bool:
    # bool é subclasse de int: True/False não podem passar como número
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def validar_registros(records) -> list[str]:
    """Retorna a lista de problemas encontrados (vazia quando a base está íntegra)."""
    if not isinstance(records, list) or not records:
        return ["Nenhum registro de tarifa encontrado."]

    erros = []
    for i, r in enumerate(records):
        prefixo = f"registro {i} ({r.get('uf')} | {r.get('concessionaria')} | {r.get('segmento')})"
        for campo in CAMPOS_TEXTO:
            if not isinstance(r.get(campo), str):
                erros.append(f"{prefixo}: campo '{campo}' deve ser texto ({r.get(campo)!r})")
        for campo in CAMPOS_NUMERICOS:
            if not _numero_valido(r.get(campo)):
                erros.append(f"{prefixo}: campo '{campo}' deve ser numérico ({r.get(campo)!r})")
        if not isinstance(r.get("cascata"), bool):
            erros.append(f"{prefixo}: campo 'cascata' deve ser true/false ({r.get('cascata')!r})")

        if _numero_valido(r.get("faixa_min")) and _numero_valido(r.get("faixa_max")):
            if r["faixa_min"] > r["faixa_max"]:
                erros.append(f"{prefixo}: faixa_min maior que faixa_max")
        for campo in ("pis_cofins", "icms"):
            if _numero_valido(r.get(campo)) and not 0 <= r[campo] < 1:
                erros.append(f"{prefixo}: {campo} fora do intervalo 0–1 ({r[campo]})")
        if _numero_valido(r.get("tarifa")) and r["tarifa"] < 0:
            erros.append(f"{prefixo}: tarifa negativa")
    return erros


def carregar_base(caminho: Path) -> BaseTarifaria:
    try:
        payload = json.loads(caminho.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise TarifasInvalidas(f"Arquivo de tarifas não encontrado: {caminho}") from exc
    except json.JSONDecodeError as exc:
        raise TarifasInvalidas(f"Arquivo de tarifas com JSON inválido: {exc}") from exc

    records = payload.get("records") if isinstance(payload, dict) else None
    erros = validar_registros(records)
    if erros:
        resumo = "\n".join(erros[:20])
        extra = f"\n... e mais {len(erros) - 20} problema(s)." if len(erros) > 20 else ""
        raise TarifasInvalidas(f"Base tarifária inválida ({caminho}):\n{resumo}{extra}")

    return BaseTarifaria(
        records=tuple(records),
        generated_at=str(payload.get("generated_at", "")),
        source=str(payload.get("source", "")),
    )


class RepositorioTarifas:
    """Mantém a base em memória e recarrega quando o arquivo é atualizado.

    Se uma atualização gerar um arquivo inválido, o erro é propagado: a
    calculadora nunca continua calculando com dados que não passaram na validação.
    """

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        self._lock = threading.Lock()
        self._assinatura = None
        self._base: BaseTarifaria | None = None

    def obter(self) -> BaseTarifaria:
        try:
            stat = self.caminho.stat()
        except FileNotFoundError as exc:
            raise TarifasInvalidas(f"Arquivo de tarifas não encontrado: {self.caminho}") from exc
        assinatura = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if assinatura != self._assinatura:
                self._base = None
                self._base = carregar_base(self.caminho)
                self._assinatura = assinatura
            return self._base
