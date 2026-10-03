"""Folios reales por tipo de archivo; si no se pueden contar, None (spec 2026-10-03 §3.9)."""
import zipfile

import fitz
from openpyxl import Workbook

from app.utils.page_counter import count_pages

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _docx(path, app_xml=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
        if app_xml is not None:
            z.writestr("docProps/app.xml", app_xml)


def test_pdf_cuenta_las_paginas_reales(tmp_path):
    path = tmp_path / "tres.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    assert count_pages(str(path), "application/pdf") == 3


def test_imagen_es_un_folio(tmp_path):
    path = tmp_path / "foto.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert count_pages(str(path), "image/png") == 1


def test_docx_usa_las_paginas_que_guarda_word(tmp_path):
    path = tmp_path / "carta.docx"
    _docx(path, '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Pages>4</Pages></Properties>')
    assert count_pages(str(path), DOCX) == 4


def test_docx_sin_conteo_no_inventa(tmp_path):
    path = tmp_path / "sin_conteo.docx"
    _docx(path)
    assert count_pages(str(path), DOCX) is None


def test_xlsx_cuenta_hojas(tmp_path):
    path = tmp_path / "libro.xlsx"
    wb = Workbook()
    wb.create_sheet("Segunda")
    wb.save(str(path))
    assert count_pages(str(path), XLSX) == 2


def test_pdf_danado_y_tipo_desconocido_no_inventan(tmp_path):
    broken = tmp_path / "roto.pdf"
    broken.write_bytes(b"no es un pdf")
    text = tmp_path / "nota.txt"
    text.write_text("hola")
    assert count_pages(str(broken), "application/pdf") is None
    assert count_pages(str(text), "text/plain") is None
