"""Si la IA no pudo leer el documento no se corre el análisis de contenido (spec 2026-10-03 §3.10)."""
import asyncio

from app.graphs.edges.documents_analysis_edges import route_after_summarize
from app.graphs.nodes.fallback_nodes import NOT_EVALUATED_MESSAGE, content_not_evaluated_node


def test_texto_vacio_o_solo_separadores_no_pasa_al_analisis():
    assert route_after_summarize({}) == "not_evaluated"
    assert route_after_summarize({"raw_text": "   \n "}) == "not_evaluated"
    assert route_after_summarize({"raw_text": "\n\n--- Página ---\n\n"}) == "not_evaluated"
    assert route_after_summarize({"raw_text": "Solicito la reparación del alumbrado."}) == "analyze"


def test_sin_texto_la_sensibilidad_queda_no_evaluado():
    result = asyncio.run(content_not_evaluated_node({"raw_text": "", "job_id": "t-1"}))
    assert result["analysis_status"] == "not_evaluated"
    assert result["sensitivity"]["level"] == "no_evaluado"
    assert result["sensitivity"]["justification"] == NOT_EVALUATED_MESSAGE


def test_archivo_no_soportado_queda_no_evaluado():
    from app.graphs.nodes.documents_analysis_nodes import unsupported_file_node

    result = asyncio.run(unsupported_file_node({"job_id": "t-2"}))
    assert result["analysis_status"] == "not_evaluated"
    assert result["sensitivity"]["level"] == "no_evaluado"
    assert result["error"]


def test_respaldo_final_del_analisis_global_queda_no_evaluado(monkeypatch):
    from app.graphs.nodes import documents_analysis_nodes as nodes

    class LLMFalla:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("LLM simulado caído")

    monkeypatch.setattr(nodes, "create_llm", lambda: LLMFalla())
    monkeypatch.setattr(nodes, "create_llm_emergency", lambda: LLMFalla())
    state = {"raw_text": "Texto", "summary": "r", "subject": "a", "job_id": "t-3"}
    result = asyncio.run(nodes.mega_analysis_node(state))
    assert result["analysis_status"] == "not_evaluated"
    assert result["sensitivity"]["level"] == "no_evaluado"
