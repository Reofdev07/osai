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
