"""Qué devuelve OSAI cuando la IA no pudo leer el documento (spec 2026-10-03 §3.10). Sin dependencias pesadas."""
from app.schemas.graph_state import DocumentState

NOT_EVALUATED_MESSAGE = "La IA no pudo leer el documento: revise y complete a mano."

NOT_EVALUATED_SENSITIVITY = {
    "level": "no_evaluado",
    "contains_sensitive_data": False,
    "detected_categories": [],
    "justification": NOT_EVALUATED_MESSAGE,
}


async def content_not_evaluated_node(state: DocumentState) -> dict:
    """Sin texto no se corre el análisis de contenido ni se supone una sensibilidad 'pública'."""
    print(f"Job [{state.get('job_id', 'N/A')}]: sin texto legible; no se evalúa el contenido.")
    return {
        "analysis_status": "not_evaluated",
        "sensitivity": dict(NOT_EVALUATED_SENSITIVITY),
        "classification": {"tipologia_documental": "", "confianza": 0},
        "tags": [],
        "entities": {},
    }
