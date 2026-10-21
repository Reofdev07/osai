"""Texto de un documento de consulta del chat (PDF o imagen que sube el funcionario para preguntar sobre él).

El archivo NO se guarda: se escribe en un temporal que se borra al terminar y no pasa por la caché de
extracciones (extract_cache). Lo único que sale de aquí es el texto, y Laravel lo guarda cifrado y con vencimiento.
"""
import os
import tempfile

import fitz

from app.core.config import positive_int_env
from app.core.llm import vision_chain
from app.graphs.nodes.documents_analysis_nodes import (
    PAGE_SEPARATOR,
    _all_pages_have_text,
    _extract_pages_with_vision,
    _pdf_page_texts,
)
from app.utils.file_guard import _mime, inspect_file
from app.utils.offload import run_cpu

REFERENCE_MAX_PAGES = positive_int_env("REFERENCE_MAX_PAGES", 20)
REFERENCE_MAX_MB = positive_int_env("REFERENCE_MAX_MB", 10)
IMAGENES = {"image/jpeg", "image/png", "image/webp"}


class ReferenceRejected(ValueError):
    """El archivo no sirve como documento de consulta; el mensaje se le muestra al funcionario."""


def _pdf_page_count(path: str) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


async def extract_reference_text(data: bytes, filename: str) -> dict:
    if not data:
        raise ReferenceRejected("El archivo está vacío.")
    if len(data) > REFERENCE_MAX_MB * 1024 * 1024:
        raise ReferenceRejected(f"El archivo supera los {REFERENCE_MAX_MB} MB.")

    suffix = os.path.splitext(filename or "")[1].lower()[:8]
    fd, path = tempfile.mkstemp(prefix="consulta_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)

        kind, reason = await run_cpu(inspect_file, path)
        if kind == "image" and _mime(path) not in IMAGENES:
            kind = "unsupported"
        if kind not in ("pdf", "image"):
            raise ReferenceRejected(reason if reason == "El archivo está vacío." else "Solo se aceptan PDF e imágenes JPG, PNG o WEBP.")
        if reason:
            raise ReferenceRejected(reason)

        if kind == "pdf":
            pages = await run_cpu(_pdf_page_count, path)
            if pages > REFERENCE_MAX_PAGES:
                raise ReferenceRejected(
                    f"El PDF tiene {pages} páginas; para consultar se aceptan hasta {REFERENCE_MAX_PAGES}."
                )
            texts = await run_cpu(_pdf_page_texts, path)
            if texts is not None and _all_pages_have_text(texts):
                text = PAGE_SEPARATOR.join(t.strip() for t in texts)
                return _result(text, len(texts), "texto")

        # Imagen o PDF escaneado: visión solo en las páginas sin texto digital.
        text, page_count, _ = await _extract_pages_with_vision(vision_chain(), path, "consulta-chat")
        return _result(text, page_count, "vision")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _result(text: str, pages: int, method: str) -> dict:
    text = (text or "").strip()
    if len(text) < 20:
        raise ReferenceRejected("No se encontró texto legible en el documento.")
    return {"text": text, "pages": pages, "method": method}
