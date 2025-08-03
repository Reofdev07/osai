
from langgraph.graph import StateGraph,  END

from app.graphs.nodes.documents_analysis_nodes import ( 
    unsupported_file_node,
    analyze_and_route_node,
    analyze_and_route_node,
    extract_from_scanned_pdf_node,
    extract_from_single_image_node,
    extract_from_text_pdf_node
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
        "unsupported": "unsupported"
    }
)

# e. Conectar los finales de cada ruta al final del workflow
workflow.add_edge("text_pdf", END)
workflow.add_edge("scanned_pdf", END)
workflow.add_edge("image", END)
workflow.add_edge("unsupported", END)

# f. Compilar el grafo para hacerlo un objeto ejecutable
app_graph = workflow.compile()
