from typing import TypedDict, List, Optional, Dict, Any, Annotated
import operator

from app.utils.token_counter import update_usage_metadata

def reduce_usage(old_usage: Optional[Dict[str, int]], new_usage: Any) -> Dict[str, int]:
    """Suma los tokens de forma acumulativa entre nodos paralelos usando el helper centralizado."""
    return update_usage_metadata(old_usage, new_usage)

def last_value_reducer(old_value: Any, new_value: Any) -> Any:
    """Conserva el último valor no nulo."""
    return new_value if new_value is not None else old_value

class DocumentState(TypedDict):
    # Input inicial
    job_id: str
    file_path: str
    
    # Procesamiento
    file_type: str                  # pdf_native, pdf_image, image, docx
    raw_text: Optional[str]         # Texto extraído
    pages: Optional[List[bytes]]    # Páginas como imágenes
    page_count: int | None   # Para contar páginas (útil en ambas rutas)
    token_count: int | None  # Para contar tokens del contenido final (caracteres aprox)
    
    # Tracking de Consumo de Servicios
    usage_metadata: Annotated[Dict[str, int], reduce_usage] # Consumo real de la IA (input, output, total)
    extraction_method: Annotated[Optional[str], last_value_reducer] # markitdown, gemini_vision, qwen_vision, google_vision_ocr
    extraction_pages: Annotated[int, operator.add] # Cantidad de páginas procesadas por el extractor
    
    step: str | None
    
    
    # Análisis IA
    summary: Optional[str]          # Resumen generado
    subject: Optional[str]           # Asunto generado
    document_date: Optional[str]     # Fecha del documento
    sentiment_analysis: Optional[Dict]  # Análisis de sentimiento e intención
    intent_analysis: Optional[Dict]  # Análisis de intención
    priority_analysis: Optional[Dict]  # Análisis de prioridad
    classification: Optional[Dict]   # Tipo de documento
    tags: Optional[List[str]]       # Tags generados
    entities: Optional[Dict]        # Entidades extraídas
    compliance_analysis: Optional[Dict]  # Análisis de cumplimiento
    sensitivity: Optional[Dict]     # Análisis de sensibilidad y datos personales
    
    # Control de flujo
    tasks_requested: List[str]      # ['classify', 'summarize', 'entities', 'tags']
    current_step: str               # Paso actual
    errors: Annotated[List[str], operator.add] # Errores acumulados (concatenados en paralelo)
