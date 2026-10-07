"""Fase 1: cadena de proveedores, topes de archivo, piso de privacidad, redacción de URLs y error al grafo."""
import asyncio
import os
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


# --- caminos para saltarse los topes (revisión de seguridad) ---
def test_pagina_gigante_se_rechaza_antes_de_renderizar(tmp_path, monkeypatch):
    import fitz
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 1_000_000)
    p = tmp_path / "g.pdf"
    d = fitz.open(); d.new_page(width=5000, height=5000); d.save(str(p))
    assert "desproporcionado" in file_guard.inspect_file(str(p))[1]

    class Pagina:  # el nodo de visión no renderiza si ni con el DPI mínimo cabe
        rect = type("R", (), {"width": 5000, "height": 5000})()
        def get_pixmap(self, **kw): raise AssertionError("no debe renderizar")
    with pytest.raises(ValueError):
        nodes._safe_dpi(Pagina())


def test_dpi_se_reduce_sin_superar_tope(monkeypatch):
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 2_000_000)
    class Pagina:
        rect = type("R", (), {"width": 600, "height": 800})()
    dpi = nodes._safe_dpi(Pagina())
    assert dpi < 200 and (600 / 72) * (800 / 72) * dpi ** 2 <= 2_000_000


def test_vision_revalida_paginas_sin_depender_del_router(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 1)
    p = tmp_path / "a.pdf"; _pdf(str(p), 2)
    with pytest.raises(ValueError):
        asyncio.run(nodes._extract_pages_with_vision([("x", object())], str(p), "j"))


def test_google_ocr_fallback_respeta_topes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 1)
    p = tmp_path / "a.pdf"; _pdf(str(p), 2)
    r = asyncio.run(nodes.extract_with_google_vision_node({"file_path": str(p), "job_id": "j"}))
    assert r["error"] and r["extraction_pages"] == 0


def _tiff(path, frames, size=(10, 10)):
    from PIL import Image
    imgs = [Image.new("RGB", size) for _ in range(frames)]
    imgs[0].save(path, save_all=True, append_images=imgs[1:])


def test_tiff_multipagina_y_gif_animado(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 3)
    t = tmp_path / "m.tiff"; _tiff(str(t), 4)
    assert "fotogramas" in file_guard.inspect_file(str(t))[1]
    _tiff(str(t), 3)
    assert file_guard.inspect_file(str(t)) == ("image", None)
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 150)  # 10x10 = 100 por fotograma; 3 fotogramas > 150*... suma
    assert file_guard.inspect_file(str(t))[1] is None
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 99)
    assert file_guard.inspect_file(str(t))[1]
    g = tmp_path / "a.gif"
    imgs = [Image.effect_noise((10, 10), 50 + i * 30).convert("P") for i in range(5)]
    imgs[0].save(g, save_all=True, append_images=imgs[1:])
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 25_000_000)
    assert "fotogramas" in file_guard.inspect_file(str(g))[1]


def test_pillow_limita_decompression_bomb(tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 5000)
    p = tmp_path / "a.png"; Image.new("RGB", (100, 100)).save(p)
    file_guard.check_image_file(str(p))
    assert Image.MAX_IMAGE_PIXELS == 5000


def test_zip_bomb_por_ratio_y_entradas(tmp_path, monkeypatch):
    z = tmp_path / "b.xlsx"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("[Content_Types].xml", "<x/>")
        f.writestr("xl/hoja.xml", "0" * 5_000_000)
    assert "sospechosa" in file_guard.inspect_file(str(z))[1]
    monkeypatch.setattr(file_guard, "MAX_ZIP_ENTRIES", 2)
    z2 = tmp_path / "c.docx"
    with zipfile.ZipFile(z2, "w") as f:
        f.writestr("[Content_Types].xml", "<x/>"); f.writestr("word/a.xml", "<x/>"); f.writestr("word/b.xml", "<x/>")
    assert "sospechosa" in file_guard.inspect_file(str(z2))[1]


def test_zip_bomb_se_valida_antes_de_markitdown(tmp_path, monkeypatch):
    z = tmp_path / "b.xlsx"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("[Content_Types].xml", "<x/>"); f.writestr("xl/hoja.xml", "0" * 5_000_000)
    r = asyncio.run(nodes.analyze_and_route_node({"file_path": str(z), "job_id": "t"}))
    assert r["fatal_error"] and r["file_type"] == "unsupported"


def test_descarga_se_corta_por_content_length_y_en_vuelo(monkeypatch):
    import httpx
    from app.utils import util
    monkeypatch.setattr(settings, "MAX_DOWNLOAD_MB", 1)
    monkeypatch.setattr(util, "is_safe_url", lambda u: True)
    enviados = []
    async def notif(**kw): enviados.append(kw)
    monkeypatch.setattr(util, "notify_steps_to_laravel", notif)
    llamado = []
    async def proceso(**kw): llamado.append(1)
    monkeypatch.setattr(util, "process_document_graph", proceso)

    def correr(handler):
        real = httpx.AsyncClient
        monkeypatch.setattr(util.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
        asyncio.run(util.stream_download_file("https://x.backblazeb2.com/a.pdf?sig=1", "j"))

    correr(lambda r: httpx.Response(200, content=b"x", headers={"content-length": str(5 * 1024 * 1024)}))
    assert enviados[-1]["status"] == "failed_terminal" and not llamado
    # Content-Length mentiroso: el tope en vuelo lo corta mientras lee el stream
    correr(lambda r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024), headers={"content-length": "10"}))
    assert len(enviados) == 2 and enviados[-1]["status"] == "failed_terminal" and not llamado


# --- fail-closed de file_guard ---
@pytest.mark.parametrize("valor", ["", "abc", "0", "-5", " ", "1.5"])
def test_config_invalida_o_cero_no_desactiva_el_tope(monkeypatch, valor):
    from app.core.config import positive_int_env
    monkeypatch.setenv("MAX_X", valor)
    assert positive_int_env("MAX_X", 60) == 60
    monkeypatch.setenv("MAX_X", "7")
    assert positive_int_env("MAX_X", 60) == 7


def test_geometria_invalida_se_rechaza():
    for w, h in [(float("nan"), 10), (float("inf"), 10), (0, 10), (-5, 10), (10, 0)]:
        assert file_guard.check_page_render(w, h)
    assert file_guard.check_page_render(595, 842) is None
    assert file_guard.check_pdf_pages(0) and file_guard.check_image_pixels(0, 10)


def test_pdf_cifrado_o_corrupto_se_rechaza(tmp_path):
    import fitz
    c = tmp_path / "c.pdf"; c.write_bytes(b"%PDF-1.4\nbasura sin estructura")
    assert file_guard.inspect_file(str(c))[1]
    e = tmp_path / "e.pdf"
    d = fitz.open(); d.new_page()
    d.save(str(e), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    assert "contraseña" in file_guard.inspect_file(str(e))[1]


def test_excepcion_inesperada_rechaza(monkeypatch, tmp_path):
    t = tmp_path / "a.txt"; t.write_text("hola")
    monkeypatch.setattr(file_guard, "_head", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert file_guard.inspect_file(str(t))[0] == "unsupported" and file_guard.inspect_file(str(t))[1]


def test_imagen_con_encabezado_mentiroso_se_rechaza(tmp_path):
    from PIL import Image
    p = tmp_path / "a.png"; Image.new("RGB", (50, 50), "red").save(p)
    data = bytearray(p.read_bytes())
    data[-30:-12] = b"\x00" * 18  # datos de imagen truncados/corruptos tras el encabezado
    p.write_bytes(bytes(data))
    assert file_guard.inspect_file(str(p))[1]


def test_texto_con_nul_tardio_y_tipo_por_contenido(tmp_path):
    t = tmp_path / "a.txt"; t.write_bytes(b"hola" * 5000 + b"\x00binario")
    assert file_guard.inspect_file(str(t))[1]
    f = tmp_path / "falso.json"; f.write_bytes(b"MZ\x90\x00\x03")  # ejecutable con extensión permitida
    assert file_guard.inspect_file(str(f))[1]
    o = tmp_path / "falso.xls"; o.write_bytes(b"texto plano")  # OLE sin firma
    assert file_guard.inspect_file(str(o))[1]


def test_zip_con_tamano_declarado_falso(tmp_path, monkeypatch):
    z = tmp_path / "f.xlsx"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as f:
        f.writestr("[Content_Types].xml", "<x/>"); f.writestr("xl/h.xml", "0" * 3_000_000)
    data = bytearray(z.read_bytes())
    # falsea file_size (uncompressed) en el directorio central a un valor diminuto
    idx = data.rindex(b"PK\x01\x02", 0, len(data))  # última entrada del directorio central
    idx = data.index(b"xl/h.xml") - 46
    data[idx + 24: idx + 28] = (10).to_bytes(4, "little")
    z.write_bytes(bytes(data))
    assert file_guard.inspect_file(str(z))[1]
    monkeypatch.setattr(file_guard, "MAX_UNCOMPRESSED_MB", 1)
    z2 = tmp_path / "g.xlsx"
    with zipfile.ZipFile(z2, "w", zipfile.ZIP_STORED) as f:
        f.writestr("[Content_Types].xml", "<x/>"); f.writestr("xl/h.xml", os.urandom(2 * 1024 * 1024))
    assert "supera" in file_guard.inspect_file(str(z2))[1]


def test_zip_anidado_cifrado_o_ruta_peligrosa(tmp_path):
    for nombre in ("xl/embeddings/bomba.zip", "xl/../../etc/x.xml"):
        z = tmp_path / "n.xlsx"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("[Content_Types].xml", "<x/>"); f.writestr("xl/h.xml", "<x/>"); f.writestr(nombre, "x")
        assert file_guard.inspect_file(str(z))[1], nombre


def test_error_inesperado_en_la_ruta_es_fatal(monkeypatch):
    monkeypatch.setattr(nodes, "inspect_file", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    r = asyncio.run(nodes.analyze_and_route_node({"file_path": "/x", "job_id": "t"}))
    assert r["fatal_error"] and r["file_type"] == "unsupported"
