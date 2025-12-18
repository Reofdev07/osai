from typing import TypedDict, List, Optional, Dict, Any

class DocumentState(TypedDict):
    # Input inicial
    job_id: str
    file_path: str
    
    # Procesamiento
    file_type: str                  # pdf_native, pdf_image, image, docx
    raw_text: Optional[str]         # Texto extraído
    pages: Optional[List[bytes]]    # Páginas como imágenes
    page_count: int | None   # Para contar páginas (útil en ambas rutas)
    token_count: int | None  # Para contar tokens del contenido final
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
    errors: List[str]               # Errores acumulados
