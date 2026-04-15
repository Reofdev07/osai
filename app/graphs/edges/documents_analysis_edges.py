from app.schemas.graph_state import DocumentState

def route_based_on_file_type(state: DocumentState) -> str:
    """
    Lee la clave 'file_type' del estado y la devuelve para el enrutamiento.
    Esta es la forma más directa y recomendada para las decisiones condicionales.
    """
    file_type = state.get("file_type")
    
    # Este log es crucial para la depuración. Te dirá exactamente qué valor se está usando para la decisión.
    print(f"--- Edge (Routing): Decidiendo ruta basada en file_type = '{file_type}' ---")
    
    # Lista de rutas válidas que el grafo conoce.
    valid_routes = ["pdf_text", "pdf_scanned", "image", "office_document", "unsupported"]
    
    if file_type in valid_routes:
        # Devuelve el valor directamente. El diccionario del grafo hará el mapeo al nodo correcto.
        return file_type
    else:
        # Si por alguna razón file_type es None o un valor inesperado,
        # lo desviamos de forma segura a la ruta 'unsupported'.
        print(f"--- Edge (Routing): ADVERTENCIA - file_type '{file_type}' no es una ruta válida. Desviando a 'unsupported'. ---")
        return "unsupported"