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


MAX_ZIP_ENTRIES = int(os.getenv("MAX_ZIP_ENTRIES", "10000"))
MAX_ZIP_RATIO = int(os.getenv("MAX_ZIP_RATIO", "200"))  # descomprimido / comprimido
MIN_RENDER_DPI = 36


def _limit_pillow() -> None:
    """Pillow avisa por encima de MAX_IMAGE_PIXELS y falla al doble: ninguna decodificación pasa de ahí."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS


def check_image_pixels(width: int, height: int) -> str | None:
    if width * height > settings.MAX_IMAGE_PIXELS:
        return f"La imagen es demasiado grande ({width}x{height}); el máximo permitido es {settings.MAX_IMAGE_PIXELS:,} píxeles."
    return None


def check_pdf_pages(pages: int) -> str | None:
    if pages > settings.MAX_PDF_PAGES:
        return f"El PDF tiene {pages} páginas; el máximo permitido es {settings.MAX_PDF_PAGES}."
    return None


def check_page_render(width_pt: float, height_pt: float) -> str | None:
    """Rechaza la página (sin renderizar) si ni con el DPI mínimo cabría en MAX_IMAGE_PIXELS."""
    pixels = (width_pt / 72) * (height_pt / 72) * MIN_RENDER_DPI ** 2
    if pixels > settings.MAX_IMAGE_PIXELS:
        return "Una página del PDF tiene un tamaño físico desproporcionado y no se puede procesar."
    return None


def check_image_file(path: str) -> str | None:
    """Dimensiones por encabezado (sin cargar píxeles) de la imagen y de cada fotograma (TIFF multipágina, GIF animado)."""
    from PIL import Image

    _limit_pillow()
    try:
        with Image.open(path) as img:
            frames = getattr(img, "n_frames", 1)
            if frames > settings.MAX_PDF_PAGES:
                return f"La imagen tiene {frames} fotogramas; el máximo permitido es {settings.MAX_PDF_PAGES}."
            total = 0
            for i in range(frames):
                img.seek(i)
                error = check_image_pixels(*img.size)
                if error:
                    return error
                total += img.size[0] * img.size[1]
            if total > settings.MAX_IMAGE_PIXELS * 4:
                return "La suma de píxeles de todos los fotogramas de la imagen excede el máximo permitido."
    except Exception:
        return "La imagen está dañada o no se puede leer."
    return None


def _inspect_pdf(path: str):
    import fitz

    try:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                return "pdf", "El PDF está protegido con contraseña."
            pages = doc.page_count
            error = check_pdf_pages(pages)
            if error:
                return "pdf", error
            for page in doc:  # solo geometría: no se renderiza nada
                error = check_page_render(page.rect.width, page.rect.height)
                if error:
                    return "pdf", error
    except Exception:
        return "pdf", "El PDF está dañado o no se puede abrir."
    return "pdf", None


def _inspect_image(path: str):
    return "image", check_image_file(path)


def _inspect_ooxml(path: str, ext: str):
    root = OOXML_ROOTS[ext]
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "[Content_Types].xml" not in names or not any(n.startswith(root) for n in names):
                return "office_document", MSG_TIPO
            infos = z.infolist()
            total = sum(i.file_size for i in infos)
            packed = sum(i.compress_size for i in infos) or 1
            if len(infos) > MAX_ZIP_ENTRIES or total / packed > MAX_ZIP_RATIO:
                return "office_document", "El documento tiene una estructura comprimida sospechosa y no se procesa."
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
