"""Cópia local da última base válida, para subir sem o Databricks.

Gravação atômica: arquivo temporário na mesma pasta + os.replace, para nunca deixar
um JSON pela metade se o processo cair no meio da escrita.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def gravar(caminho: Path, payload: dict, origem: str, carregado_em: str) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {"origem": origem, "carregado_em": carregado_em, "payload": payload}
    descritor, temporario = tempfile.mkstemp(prefix=caminho.name, suffix=".tmp", dir=caminho.parent)
    try:
        with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
            json.dump(conteudo, arquivo, ensure_ascii=False)
        os.replace(temporario, caminho)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise


def ler(caminho: Path) -> dict | None:
    """Conteúdo gravado por `gravar`, ou None se não houver cópia legível."""
    try:
        conteudo = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(conteudo, dict) or not isinstance(conteudo.get("payload"), dict):
        return None
    return conteudo
