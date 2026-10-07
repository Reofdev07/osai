"""Validación del archivo descargado por su contenido real y topes anti-DoS (C-1).

`inspect_file` devuelve (tipo, motivo_de_rechazo). Si hay motivo, el documento termina con ese error claro
en vez de colgar el proceso o caer el contenedor.
"""
import os
import zipfile

import puremagic

from app.core.config import settings

IMAGE_MIMES = {"image/png", "image/jpeg", "image/tiff", "image/webp", "image/gif", "image/bmp"}
OOXML_ROOTS = {".docx": "word/", ".xlsx": "xl/", ".pptx": "ppt/"}
OLE_EXTS = {".doc", ".xls", ".ppt"}
TEXT_EXTS = {".txt", ".csv", ".html", ".xml", ".json"}
MAX_UNCOMPRESSED_MB = int(os.getenv("MAX_UNCOMPRESSED_MB", "300"))  # anti zip-bomb en DOCX/XLSX/PPTX
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

MSG_TIPO = "El tipo de archivo no está permitido. Se aceptan PDF, imágenes (PNG, JPG, TIFF, WEBP), Word, Excel, PowerPoint y texto."


def _mime(path: str) -> str:
    try:
        return (puremagic.from_file(path, mime=True) or "").lower()
    except Exception:
        return ""


def _head(path: str, n: int = 4096) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def check_image_pixels(width: int, height: int) -> str | None:
    if width * height > settings.MAX_IMAGE_PIXELS:
        return f"La imagen es demasiado grande ({width}x{height}); el máximo permitido es {settings.MAX_IMAGE_PIXELS:,} píxeles."
    return None


def _inspect_pdf(path: str):
    import fitz

    try:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                return "pdf", "El PDF está protegido con contraseña."
            pages = doc.page_count
    except Exception:
        return "pdf", "El PDF está dañado o no se puede abrir."
    if pages > settings.MAX_PDF_PAGES:
        return "pdf", f"El PDF tiene {pages} páginas; el máximo permitido es {settings.MAX_PDF_PAGES}."
    return "pdf", None


def _inspect_image(path: str):
    from PIL import Image

    try:
        with Image.open(path) as img:  # solo lee el encabezado, no decodifica los píxeles
            width, height = img.size
    except Exception:
        return "image", "La imagen está dañada o no se puede leer."
    return "image", check_image_pixels(width, height)


def _inspect_ooxml(path: str, ext: str):
    root = OOXML_ROOTS[ext]
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "[Content_Types].xml" not in names or not any(n.startswith(root) for n in names):
                return "office_document", MSG_TIPO
            total = sum(i.file_size for i in z.infolist())
    except zipfile.BadZipFile:
        return "office_document", MSG_TIPO
    if total > MAX_UNCOMPRESSED_MB * 1024 * 1024:
        return "office_document", f"El documento descomprimido supera {MAX_UNCOMPRESSED_MB} MB."
    return "office_document", None


def inspect_file(path: str) -> tuple[str, str | None]:
    """Clasifica por contenido real: ('pdf'|'image'|'office_document'|'unsupported', motivo_de_rechazo|None)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        size = os.path.getsize(path)
        if size == 0:
            return "unsupported", "El archivo está vacío."
        if size > settings.MAX_DOWNLOAD_MB * 1024 * 1024:
            return "unsupported", f"El archivo excede el límite de {settings.MAX_DOWNLOAD_MB} MB."
        head = _head(path)
    except OSError:
        return "unsupported", "No se pudo leer el archivo."

    mime = _mime(path)
    if head.startswith(b"%PDF") or "pdf" in mime:
        return _inspect_pdf(path)
    if mime in IMAGE_MIMES:
        return _inspect_image(path)
    if ext in OOXML_ROOTS and head.startswith(b"PK"):
        return _inspect_ooxml(path, ext)
    if ext in OLE_EXTS and head.startswith(OLE_MAGIC):
        return "office_document", None
    if ext in TEXT_EXTS and b"\x00" not in head and not head.startswith(b"PK"):
        return "office_document", None
    return "unsupported", MSG_TIPO
