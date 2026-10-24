"""El catálogo de la entidad llega con cada documento, se guarda para la cola offline y no vuelve a Laravel (spec Recepción nueva §3)."""
import json

import pytest
from pydantic import ValidationError

from app.core import database, offline_queue
from app.utils.filing_catalog import FilingCatalog, without_internal_fields

CATALOGO = {
    "filing_type": "ENT",
    "dependencies": [{"id": 100, "name": "Despacho"}],
    "typologies": [{"id": 40, "name": "Petición", "code": "01", "series": "Peticiones", "subseries": None, "dependence_ids": [100]}],
}


@pytest.fixture
def base_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(database, "DB_FILE", str(tmp_path / "app_state.db"))
    database.initialize_database()


def test_la_columna_catalog_se_agrega_una_sola_vez(base_temporal):
    database.initialize_database()
    with database.get_db_connection() as conn:
        columnas = [fila[1] for fila in conn.execute("PRAGMA table_info(pending_ai_jobs)")]
    assert columnas.count("catalog") == 1


def test_el_job_guarda_el_catalogo_para_la_cola_offline(base_temporal):
    offline_queue.persist_pending_job("job-1", 7, "https://b2.test/a.pdf", CATALOGO)
    with database.get_db_connection() as conn:
        fila = conn.execute("SELECT document_id, file_url, status, catalog FROM pending_ai_jobs WHERE id = 'job-1'").fetchone()
    assert fila[:3] == (7, "https://b2.test/a.pdf", "processing")
    assert json.loads(fila[3]) == CATALOGO


def test_sin_catalogo_se_guarda_nulo(base_temporal):
    offline_queue.persist_pending_job("job-2", 8, "https://b2.test/b.pdf", None)
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT catalog FROM pending_ai_jobs WHERE id = 'job-2'").fetchone()[0] is None


def test_el_catalogo_se_valida():
    catalogo = FilingCatalog.model_validate(CATALOGO)
    assert catalogo.typologies[0].dependence_ids == [100]
    with pytest.raises(ValidationError):
        FilingCatalog.model_validate({"dependencies": [{"id": "no-es-numero", "name": "Despacho"}]})


def test_el_catalogo_no_vuelve_a_laravel_en_el_webhook():
    estado = {"job_id": "j-1", "catalog": CATALOGO, "summary": "Resumen"}
    assert without_internal_fields(estado) == {"job_id": "j-1", "summary": "Resumen"}
    assert "catalog" in estado, "No modifica el estado original."


def test_la_peticion_de_analisis_acepta_el_catalogo_opcional():
    from app.api.document_analyze.doc_analyze_router import FileUrlRequest

    assert FileUrlRequest(file_url="https://b2.test/a.pdf", document_id=7, catalog=CATALOGO).catalog.filing_type == "ENT"
    assert FileUrlRequest(file_url="https://b2.test/a.pdf", document_id=7).catalog is None


def test_un_catalogo_fuera_de_limites_se_rechaza():
    tipologia = {"id": 1, "name": "T"}
    for malo in (
        {"dependencies": [{"id": i, "name": "D"} for i in range(1001)]},
        {"typologies": [dict(tipologia, id=i) for i in range(401)]},
        {"typologies": [dict(tipologia, dependence_ids=list(range(1001)))]},
        {"typologies": [dict(tipologia, name="x" * 256)]},
        {"typologies": [dict(tipologia, code="x" * 256)]},
        {"dependencies": [{"id": 1, "name": "x" * 256}]},
    ):
        with pytest.raises(ValidationError):
            FilingCatalog.model_validate(malo)
    FilingCatalog.model_validate({"typologies": [dict(tipologia, id=i) for i in range(400)]})
    # Lo que Laravel puede enviar legítimamente (VARCHAR 255) no se rechaza.
    FilingCatalog.model_validate({"filing_type": "x" * 255, "typologies": [dict(tipologia, name="x" * 255, code="x" * 255, series="x" * 255, subseries="x" * 255)]})


def test_la_ruta_responde_422_con_un_catalogo_fuera_de_limites():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.document_analyze.doc_analyze_router import doc_analyze_router

    app = FastAPI()
    app.include_router(doc_analyze_router)
    cuerpo = {"file_url": "https://b2.test/a.pdf", "document_id": 1, "catalog": {"typologies": [{"id": i, "name": "T"} for i in range(401)]}}
    assert TestClient(app).post("/documents/analyze", json=cuerpo).status_code == 422


def test_la_migracion_tolera_la_columna_duplicada_de_otro_worker(base_temporal, monkeypatch):
    import sqlite3

    class ConexionCarrera:
        """Simula que otro worker agrega la columna entre la revisión y el ALTER."""

        def __init__(self, real):
            self.real = real

        def __getattr__(self, nombre):
            return getattr(self.real, nombre)

        def cursor(self):
            return CursorCarrera(self.real.cursor())

        def __enter__(self):
            self.real.__enter__()
            return self

        def __exit__(self, *a):
            return self.real.__exit__(*a)

    class CursorCarrera:
        def __init__(self, real):
            self.real = real

        def __getattr__(self, nombre):
            return getattr(self.real, nombre)

        def execute(self, sql, *args):
            if sql.startswith("PRAGMA table_info(pending_ai_jobs)"):
                return iter([(0, "id"), (1, "document_id")])
            return self.real.execute(sql, *args)

    # Base con la columna ya creada, pero el PRAGMA "no la ve": el ALTER falla con duplicate column.
    original = database.get_db_connection
    monkeypatch.setattr(database, "get_db_connection", lambda: ConexionCarrera(original()))
    database.initialize_database()  # no debe lanzar

    class ConexionOtroError(ConexionCarrera):
        def cursor(self):
            real = self.real.cursor()

            class C(CursorCarrera):
                def execute(inner, sql, *args):
                    if sql.startswith("ALTER TABLE"):
                        raise sqlite3.OperationalError("database is locked")
                    return CursorCarrera.execute(inner, sql, *args)

            return C(real)

    monkeypatch.setattr(database, "get_db_connection", lambda: ConexionOtroError(original()))
    with pytest.raises(sqlite3.OperationalError):
        database.initialize_database()


def test_migracion_sobre_base_antigua_conserva_las_filas(tmp_path, monkeypatch):
    import sqlite3

    ruta = str(tmp_path / "app_state.db")
    with sqlite3.connect(ruta) as conn:
        conn.execute(
            """CREATE TABLE pending_ai_jobs (id TEXT PRIMARY KEY, document_id INTEGER, file_url TEXT,
               status TEXT DEFAULT 'pending', created_at TEXT, retry_count INTEGER DEFAULT 0, last_error TEXT)"""
        )
        conn.execute("INSERT INTO pending_ai_jobs (id, document_id, file_url) VALUES ('viejo', 3, 'https://b2.test/v.pdf')")
    conn.close()
    monkeypatch.setattr(database, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(database, "DB_FILE", ruta)
    database.initialize_database()
    with database.get_db_connection() as c:
        fila = c.execute("SELECT id, document_id, catalog FROM pending_ai_jobs").fetchall()
    assert fila == [("viejo", 3, None)]


def test_process_document_graph_quita_el_catalogo_del_estado_final(monkeypatch):
    import asyncio

    from app.utils import util

    recibido = {}

    class GrafoFalso:
        async def astream(self, estado, config=None):
            recibido["inicial"] = dict(estado)
            yield {"summarize": {"summary": "Resumen"}}

    enviados = []

    async def notificar_falso(**kwargs):
        enviados.append(kwargs)

    monkeypatch.setattr(util, "app_graph", GrafoFalso())
    monkeypatch.setattr(util, "notify_steps_to_laravel", notificar_falso)

    final = asyncio.run(util.process_document_graph("/tmp/x.pdf", "job-9", CATALOGO))

    assert recibido["inicial"]["catalog"] == CATALOGO, "El grafo sí recibe el catálogo."
    assert "catalog" not in final
    assert final["summary"] == "Resumen"
    assert all("catalog" not in e["data"] for e in enviados if e["node_name"] == "graph_process")
