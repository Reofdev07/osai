"""Contrato 2 del webhook (campos aditivos: suggestion y sensibilidad TRD) y retiro de suggest-typology (spec Recepción nueva §3)."""
import asyncio
from pathlib import Path

from app.utils.notifications import CONTRACT_VERSION, build_payload

RAIZ = Path(__file__).resolve().parents[1]


def test_el_contrato_es_la_version_2():
    assert CONTRACT_VERSION == 2
    assert build_payload("job-1", "graph_process", "finished", {"suggestion": {}}, "ok")["contract_version"] == 2


def test_suggest_typology_ya_no_existe():
    from app.api.document_analyze.doc_analyze_router import doc_analyze_router

    assert not (RAIZ / "app/agents/typology_suggestion_agent.py").exists()
    assert "/documents/suggest-typology" not in [ruta.path for ruta in doc_analyze_router.routes]


def test_los_nodos_no_evaluado_devuelven_la_sugerencia_vacia_del_contrato():
    from app.graphs.nodes.documents_analysis_nodes import unsupported_file_node
    from app.graphs.nodes.fallback_nodes import content_not_evaluated_node
    from app.utils.filing_catalog import empty_suggestion

    sin_texto = asyncio.run(content_not_evaluated_node({"raw_text": "", "job_id": "t-1"}))
    no_soportado = asyncio.run(unsupported_file_node({"job_id": "t-2"}))
    assert sin_texto["suggestion"] == empty_suggestion()
    assert no_soportado["suggestion"] == empty_suggestion()


def test_un_id_mal_formado_no_hace_fallar_el_parseo_del_analisis():
    from app.schemas.agent_schemas import SuggestionOutput
    from app.utils.filing_catalog import validate_suggestion

    salida = SuggestionOutput(typology_id="no-es-un-id", dependence_id=[1], typology_confidence=0.9)
    assert salida.typology_id == "no-es-un-id"
    assert salida.dependence_id is None
    assert SuggestionOutput(typology_id={"a": 1}, dependence_id=True).model_dump()["typology_id"] is None
    assert SuggestionOutput(typology_id=True).typology_id is None
    assert SuggestionOutput(typology_id=40, dependence_id="100").dependence_id == "100"
    saneada = validate_suggestion(salida.model_dump(), {"typologies": [{"id": 40, "name": "X"}], "dependencies": []})
    assert saneada["typology_id"] is None
    assert saneada["typology_confidence"] == 0.0


def test_el_esquema_json_de_los_ids_no_tiene_nodos_sin_type():
    from app.schemas.agent_schemas import MegaEnrichmentOutput

    esquema = MegaEnrichmentOutput.model_json_schema()
    propiedades = esquema["$defs"]["SuggestionOutput"]["properties"]
    for campo in ("typology_id", "dependence_id"):
        ramas = propiedades[campo]["anyOf"]
        assert ramas and all("type" in rama for rama in ramas), propiedades[campo]
