
from langgraph.graph import StateGraph,  END

from app.graphs.nodes.documents_analysis_nodes import ( 
    unsupported_file_node,
    analyze_and_route_node,
    analyze_and_route_node,
    extract_from_scanned_pdf_node,
    extract_from_single_image_node,
    extract_from_text_pdf_node,
    summarize_and_get_subject_node,
    classify_document_node,
    tag_document_node,
    extract_entities_node,
    compliance_analysis_node
    )
from app.graphs.edges.documents_analysis_edges import (
    route_based_on_file_type
)
from app.schemas.graph_state import DocumentState





# a. Instanciar el grafo con nuestro modelo de estado
workflow = StateGraph(DocumentState)

# b. Registrar todos los nodos con un nombre único y claro
#    Nodo de Entrada:
workflow.add_node("analyze_and_route", analyze_and_route_node)

#    Nodos Trabajadores:
workflow.add_node("text_pdf", extract_from_text_pdf_node)
workflow.add_node("scanned_pdf", extract_from_scanned_pdf_node)
workflow.add_node("image", extract_from_single_image_node)
workflow.add_node("unsupported", unsupported_file_node)


# --- Nueva cadena de procesamiento ---
workflow.add_node("summarize", summarize_and_get_subject_node)
workflow.add_node("classify", classify_document_node)
workflow.add_node("tag", tag_document_node)
workflow.add_node("extract_entities", extract_entities_node)
workflow.add_node("analyze_compliance", compliance_analysis_node)

# c. Definir el punto de entrada del grafo
workflow.set_entry_point("analyze_and_route")

# d. Crear la bifurcación condicional (El corazón de la lógica)
workflow.add_conditional_edges(
    # Desde el nodo de entrada...
    "analyze_and_route",
    # ...usa nuestra función de "cartero" para decidir a dónde ir...
    route_based_on_file_type,
    # ...y aquí está el mapa de posibles destinos.
    {
        "text_pdf": "text_pdf",
        "scanned_pdf": "scanned_pdf",
        "image": "image",
        "unsupported": END
    }
)

# e. Conectar los finales de cada ruta al final del workflow
workflow.add_edge("text_pdf", "summarize")
workflow.add_edge("scanned_pdf", "summarize")
workflow.add_edge("image", "summarize")
workflow.add_edge("unsupported", END)


# e. Conectar la cadena de procesamiento linealmente
workflow.add_edge("summarize", "classify")
workflow.add_edge("classify", "tag")
workflow.add_edge("tag", "extract_entities")
workflow.add_edge("extract_entities", "analyze_compliance")
workflow.add_edge("analyze_compliance", END)

# f. Compilar el grafo para hacerlo un objeto ejecutable
app_graph = workflow.compile()
