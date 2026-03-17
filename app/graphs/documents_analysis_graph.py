from langgraph.graph import StateGraph, END
from app.schemas.graph_state import DocumentState

# --- 1. Importa todos los componentes necesarios ---

# Importa todos los nodos que definimos en el archivo anterior.
# ¡Asegúrate de que los nombres coincidan exactamente!
from app.graphs.nodes.documents_analysis_nodes import (
    analyze_and_route_node,
    extract_from_text_pdf_node,
    count_pages_node,
    adaptive_ocr_orchestrator_node,
    extract_with_google_vision_node,
    extract_with_llama_parse_node,
    update_llama_parse_usage_node,
    unsupported_file_node,
    summarize_and_get_subject_node,
    mega_analysis_node
)

# Importa la función de enrutamiento del archivo de edges.
from app.graphs.edges.documents_analysis_edges import route_based_on_file_type

# --- 2. Construcción del Grafo ---
print("Construyendo el grafo de procesamiento de documentos...")
workflow = StateGraph(DocumentState)

# --- Añadir todos los nodos al grafo ---
# Nodos de entrada y orquestación
workflow.add_node("analyze_and_route", analyze_and_route_node)
workflow.add_node("count_pages", count_pages_node)
workflow.add_node("orchestrate_ocr", adaptive_ocr_orchestrator_node)

# Nodos de extracción de texto
workflow.add_node("text_pdf", extract_from_text_pdf_node)
workflow.add_node("google_vision", extract_with_google_vision_node)
workflow.add_node("llama_parse", extract_with_llama_parse_node)
workflow.add_node("update_usage_counter", update_llama_parse_usage_node)

# Nodos de análisis de contenido
workflow.add_node("summarize", summarize_and_get_subject_node)
workflow.add_node("mega_analysis", mega_analysis_node)

# Nodos finales
workflow.add_node("unsupported", unsupported_file_node)

# --- 3. Definir las conexiones (el flujo lógico) ---

# Punto de entrada del grafo
workflow.set_entry_point("analyze_and_route")

# Decisión 1: ¿El archivo necesita OCR?
workflow.add_conditional_edges(
    "analyze_and_route",
    route_based_on_file_type,
    {
        "pdf_text": "text_pdf",
        "pdf_scanned": "count_pages",
        "image": "count_pages",
        "unsupported": "unsupported"
    }
)

# La ruta de OCR sigue un sub-flujo para decidir el proveedor
workflow.add_edge("count_pages", "orchestrate_ocr")

# Decisión 2: ¿Qué proveedor de OCR usar (decidido por el orquestador)?
def route_after_orchestration(state: DocumentState):
    provider = state.get("ocr_provider")
    print(f"--- Edge (Orchestration): Dirigiendo a '{provider}' ---")
    return provider

workflow.add_conditional_edges(
    "orchestrate_ocr",
    route_after_orchestration,
    {
        "llama_parse": "llama_parse",
        "google_vision": "google_vision"
    }
)

# La ruta de LlamaParse tiene un paso extra: actualizar el contador
workflow.add_edge("llama_parse", "update_usage_counter")

# Unificar todas las rutas de extracción para que converjan en summarize
workflow.add_edge("text_pdf", "summarize")
workflow.add_edge("google_vision", "summarize")
workflow.add_edge("update_usage_counter", "summarize")

# --- MEGA-ANALYSIS: Un solo nodo consolidado en vez de múltiples paralelos ---
# El resumen nos sirve de contexto (vía TOON) para el mega-nodo.
workflow.add_edge("summarize", "mega_analysis")
workflow.add_edge("mega_analysis", END)

# Definir los puntos finales del grafo
workflow.add_edge("unsupported", END)         # Final para archivos no soportados

# --- 4. Compilar el grafo ---
# Este es el objeto final que usarás para ejecutar tus trabajos.
app_graph = workflow.compile()

print("Grafo de procesamiento de documentos compilado y listo.")