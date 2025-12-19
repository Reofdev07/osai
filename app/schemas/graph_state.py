from typing import TypedDict, List, Optional, Dict, Any, Annotated
import operator

def reduce_usage(old_usage: Optional[Dict[str, int]], new_usage: Optional[Dict[str, int]]) -> Dict[str, int]:
    """Suma los tokens de forma acumulativa entre nodos paralelos."""
    if not old_usage: 
        return new_usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "thinking_tokens": 0}
    if not new_usage: 
        return old_usage
    return {
        "input_tokens": old_usage.get("input_tokens", 0) + new_usage.get("input_tokens", 0),
        "output_tokens": old_usage.get("output_tokens", 0) + new_usage.get("output_tokens", 0),
        "total_tokens": old_usage.get("total_tokens", 0) + new_usage.get("total_tokens", 0),
        "thinking_tokens": old_usage.get("thinking_tokens", 0) + new_usage.get("thinking_tokens", 0),
    }

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
    usage_metadata: Annotated[Dict[str, int], reduce_usage] # Consumo real de la IA (input, output, total)
    step: str | None
    
    ocr_provider: Optional[str] | None # google_vision, llama_parse
    ocr_provider_decision: Optional[str] | None # llama_parse, google_vision
    
    
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
    
    # Control de flujo
    tasks_requested: List[str]      # ['classify', 'summarize', 'entities', 'tags']
    current_step: str               # Paso actual
    errors: Annotated[List[str], operator.add] # Errores acumulados (concatenados en paralelo)
