from typing import Literal

from app.schemas.graph_state import DocumentState

def decide_extraction_path(state: DocumentState) -> Literal["extract_pdf", "extract_image", "unsupported_end"]:
    """
    Esta función lee el estado y decide cuál es el siguiente nodo a ejecutar.
    """
    if state.get("error"):
        return "unsupported_end"
        
    file_type = state["file_type"]
    if file_type == "pdf":
        return "extract_pdf"
    else:
        return "extract_image"



def route_based_on_file_type(state: DocumentState) -> Literal["text_pdf", "scanned_pdf", "image", "unsupported"]:
    """
    Lee el tipo de archivo del estado y devuelve el nombre de la siguiente ruta.
    """
    file_type = state["file_type"]

    # Mapeamos los tipos de estado a los nombres de los nodos que usaremos en el grafo
    if file_type == "pdf_text":
        return "text_pdf"
    elif file_type == "pdf_scanned":
        return "scanned_pdf"
    elif file_type == "image":
        return "image"
    else:
        return "unsupported"