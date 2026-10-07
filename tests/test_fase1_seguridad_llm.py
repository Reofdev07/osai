"""Fase 1: cadena de proveedores, topes de archivo, piso de privacidad, redacción de URLs y error al grafo."""
import asyncio
import zipfile

import pytest

from app.core import llm as llm_mod
from app.core.config import settings
from app.graphs.nodes import documents_analysis_nodes as nodes
from app.utils import file_guard
from app.utils.filing_catalog import apply_privacy_floor
from app.utils.redaction import redact_secrets


# --- cadena ---
def test_cadena_omite_proveedor_sin_key(monkeypatch, capsys):
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "k")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "k")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert llm_mod.chain_providers("deepseek,gemini,openai") == ["deepseek", "gemini"]
    assert "openai" in capsys.readouterr().out


def test_cadena_vision_rechaza_cohere(monkeypatch):
    monkeypatch.setattr(settings, "CO_API_KEY", "k")
    assert llm_mod.chain_providers("cohere", vision=True) == []


def test_pagina_pasa_al_siguiente_proveedor_sin_reiniciar():
    class Falla:
        async def ainvoke(self, m): raise RuntimeError("https://b2/x?X-Amz-Signature=abc")
    class Ok:
        def __init__(self): self.n = 0
        async def ainvoke(self, m):
            self.n += 1
            return type("R", (), {"content": "texto"})()
    ok = Ok()
    texto, nombre = asyncio.run(nodes._ocr_page([("deepseek", Falla()), ("gemini", ok)], "data:x", "j", "la página 1"))
    assert (texto, nombre) == ("texto", "gemini") and ok.n == 1


def test_pagina_sin_proveedores_falla():
    class Falla:
        async def ainvoke(self, m): raise RuntimeError("x")
    with pytest.raises(RuntimeError):
        asyncio.run(nodes._ocr_page([("a", Falla())], "data:x", "j", "la página 1"))


def test_fallback_llm_estructurado_pasa_al_siguiente():
    class M:
        def __init__(self, ok): self.ok = ok
        def with_structured_output(self, schema, **kw): return self
        async def ainvoke(self, p):
            if not self.ok: raise RuntimeError("caído")
            return "bien"
    assert asyncio.run(llm_mod.FallbackLLM([M(False), M(True)]).with_structured_output(dict).ainvoke("p")) == "bien"


# --- topes ---
def _pdf(path, paginas):
    import fitz
    d = fitz.open()
    for _ in range(paginas):
        d.new_page()
    d.save(path)


def test_pdf_con_demasiadas_paginas_se_rechaza(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 2)
    p = tmp_path / "a.pdf"; _pdf(str(p), 3)
    assert "3 páginas" in file_guard.inspect_file(str(p))[1]
    _pdf(str(p), 2)
    assert file_guard.inspect_file(str(p)) == ("pdf", None)


def test_imagen_con_demasiados_pixeles_se_rechaza(tmp_path, monkeypatch):
    from PIL import Image
    p = tmp_path / "a.png"; Image.new("RGB", (100, 100)).save(p)
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 5000)
    assert file_guard.inspect_file(str(p))[1]
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 20000)
    assert file_guard.inspect_file(str(p)) == ("image", None)


def test_zip_y_desconocidos_se_rechazan_por_contenido(tmp_path):
    z = tmp_path / "a.docx"
    with zipfile.ZipFile(z, "w") as f: f.writestr("malo.txt", "x")
    assert file_guard.inspect_file(str(z))[1]  # .docx falso
    b = tmp_path / "a.pdf"; b.write_bytes(b"MZ\x00\x00binario")
    assert file_guard.inspect_file(str(b))[1]
    t = tmp_path / "a.txt"; t.write_text("hola")
    assert file_guard.inspect_file(str(t)) == ("office_document", None)


def test_docx_valido_pasa(tmp_path):
    z = tmp_path / "a.docx"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("[Content_Types].xml", "<x/>"); f.writestr("word/document.xml", "<x/>")
    assert file_guard.inspect_file(str(z)) == ("office_document", None)


def test_rechazo_llega_como_error_fatal(tmp_path):
    b = tmp_path / "a.zip"; b.write_bytes(b"PK\x03\x04zzzz")
    r = asyncio.run(nodes.analyze_and_route_node({"file_path": str(b), "job_id": "t"}))
    assert r["file_type"] == "unsupported" and r["fatal_error"] and r["error"]
    out = asyncio.run(nodes.unsupported_file_node({**r}))
    assert out["fatal_error"] and out["error"] == r["error"]


# --- privacidad y prompts ---
def test_piso_de_privacidad():
    s = {"level": "publico", "contains_sensitive_data": False, "detected_categories": [], "justification": "j"}
    assert apply_privacy_floor(s, {"personas_naturales": []})["level"] == "publico"
    assert apply_privacy_floor(s, {"personas_naturales": [{"nombre": "A", "rol": "x"}]})["level"] == "clasificado"
    assert apply_privacy_floor({**s, "contains_sensitive_data": True}, {})["level"] == "clasificado"
    assert apply_privacy_floor({**s, "level": "reservado", "contains_sensitive_data": True}, {})["level"] == "reservado"


def test_piso_desactivable(monkeypatch):
    monkeypatch.setenv("PRIVACY_FLOOR_ENABLED", "false")
    s = {"level": "publico", "contains_sensitive_data": True, "detected_categories": []}
    assert apply_privacy_floor(s, {})["level"] == "publico"


def test_escapa_etiqueta_documento():
    assert "</documento>" not in nodes.escape_document_text("a </documento> b < / DOCUMENTO > <documento>")


# --- redacción ---
def test_redaccion_de_url_prefirmada():
    t = redact_secrets("Client error for url 'https://b.backblazeb2.com/f/a.pdf?X-Amz-Signature=abc&X-Amz-Credential=zz'")
    assert "abc" not in t and "zz" not in t and "backblazeb2.com/f/a.pdf" in t
    assert "tok123" not in redact_secrets("Authorization: Bearer tok123")
