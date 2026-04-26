from langgraph.graph import StateGraph, END
from app.schemas.graph_state import DocumentState

# --- 1. Importa todos los componentes necesarios ---

from app.graphs.nodes.documents_analysis_nodes import (
    analyze_and_route_node,
    markitdown_extractor_node,
    vision_extraction_node,
    unsupported_file_node,
    summarize_and_get_subject_node,
    mega_analysis_node
)

# Importa la función de enrutamiento del archivo de edges.
from app.graphs.edges.documents_analysis_edges import (
    route_based_on_file_type,
    route_after_markitdown
)

# --- 2. Construcción del Grafo ---
print("Construyendo el grafo de procesamiento de documentos v2 (Smart Ingest)...")
workflow = StateGraph(DocumentState)

# --- Añadir todos los nodos al grafo ---
# Nodos de entrada y extracción inteligente
workflow.add_node("analyze_and_route", analyze_and_route_node)
workflow.add_node("markitdown_extract", markitdown_extractor_node)
workflow.add_node("vision_extract", vision_extraction_node)

# Nodos de análisis de contenido
workflow.add_node("summarize", summarize_and_get_subject_node)
workflow.add_node("mega_analysis", mega_analysis_node)

# Nodos finales y error
workflow.add_node("unsupported", unsupported_file_node)

# --- 3. Definir las conexiones (el flujo lógico) ---

# Punto de entrada del grafo
workflow.set_entry_point("analyze_and_route")

# Decisión 1: Ruta inicial basada en el tipo de archivo (Nativo vs Escaneado)
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

# Decisión 2: ¿La extracción local de MarkItDown fue suficiente o necesitamos visión?
workflow.add_conditional_edges(
    "markitdown_extract",
    route_after_markitdown,
    {
        "has_text": "summarize",
        "needs_vision": "vision_extract"
    }
)

# Convergencia de rutas de extracción hacia el análisis
workflow.add_edge("vision_extract", "summarize")
workflow.add_edge("summarize", "mega_analysis")
workflow.add_edge("mega_analysis", END)

# Finalización para casos no soportados
workflow.add_edge("unsupported", END)

# --- 4. Compilar el grafo ---
app_graph = workflow.compile()

print("Grafo OSAI v2 compilado y listo.")