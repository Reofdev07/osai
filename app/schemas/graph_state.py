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
    
    
    # Análisis IA
    summary: Optional[str]          # Resumen generado
    subject: Optional[str]           # Asunto generado
    classification: Optional[Dict]   # Tipo de documento
    tags: Optional[List[str]]       # Tags generados
    entities: Optional[List[Dict]]  # Entidades extraídas
    compliance_analysis: Optional[Dict]  # Análisis de cumplimiento
    
    # Control de flujo
    tasks_requested: List[str]      # ['classify', 'summarize', 'entities', 'tags']
    current_step: str               # Paso actual
    errors: List[str]               # Errores acumulados
