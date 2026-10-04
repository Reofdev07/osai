"""El análisis global pone el catálogo en el prompt y devuelve la sugerencia validada (spec Recepción nueva §3)."""
import asyncio
from types import SimpleNamespace

from app.graphs.nodes import documents_analysis_nodes as nodes
from app.schemas.agent_schemas import MegaEnrichmentOutput

CATALOGO = {
    "filing_type": "SAL",
    "dependencies": [{"id": 100, "name": "Despacho"}],
    "typologies": [{"id": 41, "name": "Circular", "code": "02", "series": "Circulares", "subseries": None, "dependence_ids": [100]}],
}


def _salida(sugerencia=None, nivel="clasificado"):
    return MegaEnrichmentOutput(
        intencion={"intencion": "Informar", "justificacion": "Comunica una decisión"},
        sentimiento_urgencia={"etiqueta": "Neutro", "puntuacion": 0, "justificacion": "", "urgencia_nivel": "Media", "urgencia_justificacion": ""},
        clasificacion={"tipologia_documental": "Nombre inventado", "confianza": 0.4},
        etiquetas=["circular"],
        entidades={},
        prioridad={"prioridad": "Media", "justificacion_legal": "Ley 1755 de 2015", "termino_respuesta_sugerido_dias": 10},
        conformidad={"cumple_normativa": True, "resumen_ejecutivo": "", "analisis_detallado": ""},
        sensibilidad={"level": nivel, "contains_sensitive_data": False, "detected_categories": [], "justification": "Sin datos personales"},
        sugerencia=sugerencia or {},
    )


class LLMFalso:
    def __init__(self, salida):
        self.salida = salida
        self.prompts = []

    def with_structured_output(self, *args, **kwargs):
        return self

    async def ainvoke(self, prompt):
        self.prompts.append(prompt)
        return {"parsed": self.salida, "raw": SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})}


def _analizar(monkeypatch, salida, catalogo):
    llm = LLMFalso(salida)
    monkeypatch.setattr(nodes, "create_llm", lambda: llm)
    estado = {"raw_text": "Circular 004 sobre horarios.", "summary": "Circular", "subject": "Horarios", "job_id": "t-1", "catalog": catalogo}
    return asyncio.run(nodes.mega_analysis_node(estado)), llm


def test_el_prompt_incluye_el_catalogo_fuera_del_documento(monkeypatch):
    _, llm = _analizar(monkeypatch, _salida(), CATALOGO)
    prompt = llm.prompts[0]
    assert "- [41] Circular (código 02)" in prompt
    assert prompt.index("CATÁLOGO DE LA ENTIDAD (use SOLO") < prompt.rindex("<documento>")
    assert "produce y firma" in prompt


def test_la_salida_trae_la_sugerencia_validada_y_el_nombre_del_catalogo(monkeypatch):
    resultado, _ = _analizar(monkeypatch, _salida({"typology_id": 41, "typology_confidence": 0.91, "dependence_id": 999, "dependence_confidence": 0.9, "sender": {"name": "Despacho del alcalde", "kind": "entidad"}, "sender_confidence": 0.6}), CATALOGO)
    assert resultado["suggestion"]["typology_id"] == 41
    assert (resultado["suggestion"]["dependence_id"], resultado["suggestion"]["dependence_confidence"]) == (100, 0.91)
    assert resultado["classification"] == {"tipologia_documental": "Circular", "confianza": 0.91}
    assert resultado["sensitivity"]["level"] == "clasificado"


def test_sin_catalogo_no_falla_ni_sugiere_ids(monkeypatch):
    resultado, llm = _analizar(monkeypatch, _salida({"typology_id": 41, "typology_confidence": 0.9}, nivel="public"), None)
    assert "Tipologías documentales (typology_id):" not in llm.prompts[0]
    assert resultado["suggestion"]["typology_id"] is None
    assert resultado["classification"]["tipologia_documental"] == "Nombre inventado"
    assert resultado["sensitivity"]["level"] == "publico"


def test_el_respaldo_por_defecto_trae_sugerencia_vacia(monkeypatch):
    class LLMCaido:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("LLM simulado caído")

    monkeypatch.setattr(nodes, "create_llm", lambda: LLMCaido())
    monkeypatch.setattr(nodes, "create_llm_emergency", lambda: LLMCaido())
    resultado = asyncio.run(nodes.mega_analysis_node({"raw_text": "Texto", "summary": "r", "subject": "a", "job_id": "t-2", "catalog": CATALOGO}))
    assert resultado["suggestion"]["typology_id"] is None
    assert resultado["sensitivity"]["level"] == "no_evaluado"
    assert resultado["analysis_status"] == "not_evaluated"
