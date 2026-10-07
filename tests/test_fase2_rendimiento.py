"""Fase 2: nada bloquea el event loop, visión por página en paralelo, imágenes livianas, detección por página y caché por hash."""
import asyncio
import base64
import os
import stat
import time

import pytest

from app.core.config import settings
from app.graphs.nodes import documents_analysis_nodes as nodes
from app.utils import extract_cache

TEXTO = "Texto digital de la pagina con suficientes caracteres para superar el umbral minimo. " * 2


def _pdf(path, paginas):
    """paginas: lista de bool (True = con texto, False = escaneada/en blanco)."""
    import fitz
    d = fitz.open()
    for con_texto in paginas:
        p = d.new_page()
        if con_texto:
            p.insert_text((72, 72), TEXTO, fontsize=9)
    d.save(path)


class Resp:
    def __init__(self, c): self.content = c


def _pagina_de(messages):
    url = messages[0]["content"][1]["image_url"]["url"]
    return base64.b64decode(url.split(",", 1)[1]).decode()


@pytest.fixture(autouse=True)
def _cache_aislada(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXTRACT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EXTRACT_CACHE_DAYS", 7)


# --- defaults ---
def test_valores_por_defecto():
    assert settings.OSAI_CPU_THREADS == 4
    assert settings.VISION_PAGE_CONCURRENCY == 3
    assert settings.VISION_DPI == 150 and settings.VISION_JPEG_QUALITY == 85
    assert settings.TEXT_PAGE_MIN_CHARS == 50 and settings.PDF_SKIP_MARKITDOWN is True
    assert settings.LLM_RATE_LIMIT_RPS == 1.0


# --- C-2: el event loop no se bloquea ---
async def _latido_maximo(coro):
    huecos, activo = [], True

    async def latido():
        previo = time.monotonic()
        while activo:
            await asyncio.sleep(0.02)
            ahora = time.monotonic()
            huecos.append(ahora - previo)
            previo = ahora
    t = asyncio.create_task(latido())
    try:
        resultado = await coro
    finally:
        activo = False
        await t
    return resultado, max(huecos)


def test_ruta_no_bloquea_el_loop(tmp_path, monkeypatch):
    p = tmp_path / "a.pdf"; _pdf(str(p), [True])
    def lento(path):
        time.sleep(0.8); return "pdf", None
    monkeypatch.setattr(nodes, "inspect_file", lento)
    _, hueco = asyncio.run(_latido_maximo(nodes.analyze_and_route_node({"file_path": str(p), "job_id": "t"})))
    assert hueco < 0.5


def test_markitdown_y_tokens_no_bloquean_el_loop(tmp_path, monkeypatch):
    t = tmp_path / "a.txt"; t.write_text("hola " * 100)
    class Lento:
        def convert(self, path):
            time.sleep(0.8)
            return type("R", (), {"text_content": "contenido " * 30})()
    monkeypatch.setattr(nodes, "MarkItDown", Lento)
    r, hueco = asyncio.run(_latido_maximo(nodes.markitdown_extractor_node({"file_path": str(t), "job_id": "t"})))
    assert r["extraction_method"] == "markitdown" and hueco < 0.5


def test_render_y_vision_no_bloquean_el_loop(tmp_path, monkeypatch):
    p = tmp_path / "a.pdf"; _pdf(str(p), [False, False])
    def lento(path, index, dpi, quality):
        time.sleep(0.6); return b"x"
    monkeypatch.setattr(nodes, "_render_page_jpeg", lento)
    class Ok:
        async def ainvoke(self, m): return Resp("t")
    _, hueco = asyncio.run(_latido_maximo(nodes._extract_pages_with_vision([("g", Ok())], str(p), "j")))
    assert hueco < 0.4


# --- paralelo, orden y 429 ---
def test_paginas_en_paralelo_acotado_y_en_orden(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "VISION_PAGE_CONCURRENCY", 3)
    p = tmp_path / "a.pdf"; _pdf(str(p), [False] * 7)
    monkeypatch.setattr(nodes, "_render_page_jpeg", lambda path, i, dpi, q: f"pag{i}".encode())
    estado = {"activas": 0, "max": 0}

    class Chain:
        async def ainvoke(self, m):
            n = int(_pagina_de(m)[3:])
            estado["activas"] += 1; estado["max"] = max(estado["max"], estado["activas"])
            await asyncio.sleep(0.2 - n * 0.02)  # las primeras tardan más: el orden no debe depender de quién termina antes
            estado["activas"] -= 1
            return Resp(f"T{n}")
    texto, paginas, usados = asyncio.run(nodes._extract_pages_with_vision([("g", Chain())], str(p), "j"))
    assert estado["max"] == 3 and paginas == 7 and usados == {"g"}
    assert texto == "\n\n--- Página ---\n\n".join(f"T{i}" for i in range(7))


def test_429_espera_y_reintenta_el_mismo_proveedor_sin_repetir_paginas(tmp_path, monkeypatch):
    p = tmp_path / "a.pdf"; _pdf(str(p), [False, False])
    monkeypatch.setattr(nodes, "_render_page_jpeg", lambda path, i, dpi, q: f"pag{i}".encode())
    esperas = []
    async def dormir(s): esperas.append(s)
    monkeypatch.setattr(nodes.asyncio, "sleep", dormir)

    class E429(Exception):
        status_code = 429
    llamadas = {"a": [], "b": []}

    class A:
        async def ainvoke(self, m):
            n = _pagina_de(m); llamadas["a"].append(n)
            if n == "pag0" and llamadas["a"].count("pag0") == 1:
                raise E429("rate")
            return Resp("A" + n)
    class B:
        async def ainvoke(self, m): llamadas["b"].append(1); return Resp("B")
    texto, _, usados = asyncio.run(nodes._extract_pages_with_vision([("a", A()), ("b", B())], str(p), "j"))
    assert llamadas["a"].count("pag0") == 2 and llamadas["a"].count("pag1") == 1
    assert llamadas["b"] == [] and usados == {"a"} and esperas


def test_429_persistente_acota_reintentos_y_pasa_al_siguiente(monkeypatch):
    async def dormir(s): pass
    monkeypatch.setattr(nodes.asyncio, "sleep", dormir)
    monkeypatch.setattr(settings, "VISION_429_RETRIES", 2)
    class E429(Exception):
        status_code = 429
    n = {"a": 0}
    class A:
        async def ainvoke(self, m): n["a"] += 1; raise E429("x")
    class B:
        async def ainvoke(self, m): return Resp("ok")
    texto, nombre = asyncio.run(nodes._ocr_page([("a", A()), ("b", B())], "data:x", "j", "p"))
    assert n["a"] == 3 and (texto, nombre) == ("ok", "b")


# --- JPEG liviano ---
def test_render_jpeg_con_dpi_y_calidad(tmp_path):
    p = tmp_path / "a.pdf"; _pdf(str(p), [True])
    datos = nodes._render_page_jpeg(str(p), 0, 100, 60)
    assert datos[:2] == b"\xff\xd8"
    assert len(nodes._render_page_jpeg(str(p), 0, 150, 85)) > len(datos)


def test_url_de_pagina_es_jpeg(tmp_path, monkeypatch):
    p = tmp_path / "a.pdf"; _pdf(str(p), [False])
    vistas = []
    class Chain:
        async def ainvoke(self, m): vistas.append(m[0]["content"][1]["image_url"]["url"]); return Resp("t")
    asyncio.run(nodes._extract_pages_with_vision([("g", Chain())], str(p), "j"))
    assert vistas[0].startswith("data:image/jpeg;base64,")


# --- detección por página ---
def test_pdf_mixto_solo_envia_a_vision_las_paginas_escaneadas(tmp_path, monkeypatch):
    p = tmp_path / "m.pdf"; _pdf(str(p), [True, False, True, False])
    monkeypatch.setattr(nodes, "_render_page_jpeg", lambda path, i, dpi, q: f"pag{i}".encode())
    vistas = []
    class Chain:
        async def ainvoke(self, m): vistas.append(_pagina_de(m)); return Resp("OCR" + _pagina_de(m))
    texto, paginas, usados = asyncio.run(nodes._extract_pages_with_vision([("g", Chain())], str(p), "j"))
    assert sorted(vistas) == ["pag1", "pag3"] and paginas == 4
    partes = texto.split("\n\n--- Página ---\n\n")
    assert len(partes) == 4 and "Texto digital" in partes[0] and partes[1] == "OCRpag1"
    assert "Texto digital" in partes[2] and partes[3] == "OCRpag3"


def test_markitdown_se_salta_si_todas_las_paginas_tienen_texto(tmp_path, monkeypatch):
    p = tmp_path / "t.pdf"; _pdf(str(p), [True, True])
    class Boom:
        def convert(self, path): raise AssertionError("no debe correr MarkItDown")
    monkeypatch.setattr(nodes, "MarkItDown", Boom)
    r = asyncio.run(nodes.markitdown_extractor_node({"file_path": str(p), "job_id": "t", "page_count": 2}))
    assert r["extraction_method"] == "markitdown" and "Texto digital" in r["raw_text"] and r["error"] is None


def test_markitdown_corre_si_el_flag_esta_apagado(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PDF_SKIP_MARKITDOWN", False)
    p = tmp_path / "t.pdf"; _pdf(str(p), [True])
    usado = []
    class Fake:
        def convert(self, path): usado.append(1); return type("R", (), {"text_content": "x" * 80})()
    monkeypatch.setattr(nodes, "MarkItDown", Fake)
    r = asyncio.run(nodes.markitdown_extractor_node({"file_path": str(p), "job_id": "t"}))
    assert usado and r["raw_text"] == "x" * 80


def test_pdf_escaneado_o_mixto_va_a_vision_sin_correr_markitdown(tmp_path, monkeypatch):
    class Boom:
        def convert(self, path): raise AssertionError("no debe correr MarkItDown")
    monkeypatch.setattr(nodes, "MarkItDown", Boom)
    for paginas in ([False, False], [True, False]):
        p = tmp_path / f"{len(paginas)}{paginas[0]}.pdf"; _pdf(str(p), paginas)
        r = asyncio.run(nodes.markitdown_extractor_node({"file_path": str(p), "job_id": "t"}))
        assert r["extraction_method"] == "markitdown_empty" and r["raw_text"] == ""


def test_umbral_de_texto_configurable(tmp_path, monkeypatch):
    p = tmp_path / "t.pdf"; _pdf(str(p), [True])
    monkeypatch.setattr(settings, "TEXT_PAGE_MIN_CHARS", 100000)
    r = asyncio.run(nodes.markitdown_extractor_node({"file_path": str(p), "job_id": "t"}))
    assert r["extraction_method"] == "markitdown_empty"


# --- caché por hash ---
def test_cache_evita_repagar_la_vision_y_es_privada(tmp_path, monkeypatch):
    p = tmp_path / "e.pdf"; _pdf(str(p), [False, False])
    monkeypatch.setattr(nodes, "_render_page_jpeg", lambda path, i, dpi, q: b"x")
    n = {"c": 0}
    class Chain:
        async def ainvoke(self, m): n["c"] += 1; return Resp("contenido secreto")
    monkeypatch.setattr(nodes, "vision_chain", lambda: [("g", Chain())])
    r1 = asyncio.run(nodes.vision_extraction_node({"file_path": str(p), "job_id": "j"}))
    r2 = asyncio.run(nodes.vision_extraction_node({"file_path": str(p), "job_id": "j2"}))
    assert n["c"] == 2 and r1 == r2 and r1["raw_text"].count("contenido secreto") == 2
    carpeta = settings.EXTRACT_CACHE_DIR
    archivos = os.listdir(carpeta)
    assert len(archivos) == 1
    assert stat.S_IMODE(os.stat(os.path.join(carpeta, archivos[0])).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(carpeta).st_mode) == 0o700
    assert "http" not in open(os.path.join(carpeta, archivos[0])).read()


def test_cache_no_guarda_fallos_ni_si_esta_apagada(tmp_path, monkeypatch):
    p = tmp_path / "e.pdf"; _pdf(str(p), [False])
    monkeypatch.setattr(nodes, "_render_page_jpeg", lambda path, i, dpi, q: b"x")
    class Mal:
        async def ainvoke(self, m): raise RuntimeError("x")
    monkeypatch.setattr(nodes, "vision_chain", lambda: [("g", Mal())])
    r = asyncio.run(nodes.vision_extraction_node({"file_path": str(p), "job_id": "j"}))
    assert r["error"] and not os.path.exists(settings.EXTRACT_CACHE_DIR) or not os.listdir(settings.EXTRACT_CACHE_DIR)
    monkeypatch.setattr(settings, "EXTRACT_CACHE_DAYS", 0)
    class Ok:
        async def ainvoke(self, m): return Resp("t")
    monkeypatch.setattr(nodes, "vision_chain", lambda: [("g", Ok())])
    asyncio.run(nodes.vision_extraction_node({"file_path": str(p), "job_id": "j"}))
    assert not os.path.exists(settings.EXTRACT_CACHE_DIR) or not os.listdir(settings.EXTRACT_CACHE_DIR)


def test_cache_ttl_y_tope_de_tamano(tmp_path, monkeypatch):
    clave = "a" * 64
    extract_cache.save(clave, {"raw_text": "hola"})
    assert extract_cache.load(clave) == {"raw_text": "hola"}
    ruta = os.path.join(settings.EXTRACT_CACHE_DIR, clave + ".json")
    viejo = time.time() - 8 * 86400
    os.utime(ruta, (viejo, viejo))
    assert extract_cache.load(clave) is None and not os.path.exists(ruta)
    monkeypatch.setattr(settings, "EXTRACT_CACHE_MAX_MB", 1)
    for i in range(5):
        extract_cache.save(f"{i:064d}", {"raw_text": "x" * 400_000})
        antes = time.time() - 1000 + i  # las ya guardadas quedan más antiguas que la nueva
        if os.path.exists(os.path.join(settings.EXTRACT_CACHE_DIR, f"{i:064d}.json")):
            os.utime(os.path.join(settings.EXTRACT_CACHE_DIR, f"{i:064d}.json"), (antes, antes))
    total = sum(os.path.getsize(os.path.join(settings.EXTRACT_CACHE_DIR, f)) for f in os.listdir(settings.EXTRACT_CACHE_DIR))
    assert total <= 1024 * 1024


def test_cache_rechaza_claves_raras():
    assert extract_cache.load("../../etc/passwd") is None
    extract_cache.save("../x", {"raw_text": "x"})
    assert not os.path.exists(os.path.join(settings.EXTRACT_CACHE_DIR, "..", "x.json"))


# --- medición ---
def test_metricas_sin_contenido(tmp_path, monkeypatch, capsys):
    p = tmp_path / "m.pdf"; _pdf(str(p), [True, False])
    monkeypatch.setattr(nodes, "_render_page_jpeg", lambda path, i, dpi, q: b"x")
    class Chain:
        async def ainvoke(self, m): return Resp("CONTENIDO-SECRETO-OCR")
    asyncio.run(nodes._extract_pages_with_vision([("gemini", Chain())], str(p), "job9"))
    out = capsys.readouterr().out
    linea = next(l for l in out.splitlines() if "Métricas" in l)
    assert "job9" in linea and "páginas=2" in linea and "visión=1" in linea and "gemini" in linea and "segundos=" in linea
    assert "CONTENIDO-SECRETO" not in out and "Texto digital" not in out
