from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from app.schemas.graph_state import DocumentState
import aiosqlite
import os

_checkpointer: AsyncSqliteSaver | None = None


async def init_checkpointer() -> AsyncSqliteSaver:
    global _checkpointer
    if _checkpointer is None:
        os.makedirs("data", exist_ok=True)
        conn = await aiosqlite.connect("data/graph_checkpoints.db")
        _checkpointer = AsyncSqliteSaver(conn)
        app_graph.checkpointer = _checkpointer
        print("Checkpointer AsyncSqliteSaver inicializado.")
    return _checkpointer


# --- 1. Importa todos los componentes necesarios ---

from app.graphs.nodes.documents_analysis_nodes import (
    analyze_and_route_node,
    markitdown_extractor_node,
    vision_extraction_node,
    unsupported_file_node,
    summarize_and_get_subject_node,
    mega_analysis_node
)

from app.graphs.edges.documents_analysis_edges import (
    route_based_on_file_type,
    route_after_markitdown
)

# --- 2. Construcción del Grafo ---
print("Construyendo el grafo de procesamiento de documentos v2 (Smart Ingest)...")
workflow = StateGraph(DocumentState)

# --- Añadir todos los nodos al grafo ---
workflow.add_node("analyze_and_route", analyze_and_route_node)
workflow.add_node("markitdown_extract", markitdown_extractor_node)
workflow.add_node("vision_extract", vision_extraction_node)
workflow.add_node("summarize", summarize_and_get_subject_node)
workflow.add_node("mega_analysis", mega_analysis_node)
workflow.add_node("unsupported", unsupported_file_node)

# --- 3. Definir las conexiones ---
workflow.set_entry_point("analyze_and_route")

workflow.add_conditional_edges(
    "analyze_and_route",
    route_based_on_file_type,
    {
        "pdf_text": "markitdown_extract",
        "office_document": "markitdown_extract",
        "pdf_scanned": "vision_extract",
        "image": "vision_extract",
        "unsupported": "unsupported"
    }
)

workflow.add_conditional_edges(
    "markitdown_extract",
    route_after_markitdown,
    {
        "has_text": "summarize",
        "needs_vision": "vision_extract"
    }
)

workflow.add_edge("vision_extract", "summarize")
workflow.add_edge("summarize", "mega_analysis")
workflow.add_edge("mega_analysis", END)
workflow.add_edge("unsupported", END)

# --- 4. Compilar sin checkpointer (se inyecta en init_checkpointer) ---
app_graph = workflow.compile()

print("Grafo OSAI v2 compilado. Checkpointer se inyecta en startup.")