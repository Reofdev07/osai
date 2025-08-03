from typing import TypedDict, List, Optional, Dict, Any

class DocumentState(TypedDict):
    # Input inicial
    file_data: Dict[str, Any]       # Metadata del archivo
    file_content: bytes             # Contenido binario
    
    # Procesamiento
    file_type: str                  # pdf_native, pdf_image, image, docx
    raw_text: Optional[str]         # Texto extraído
    pages: Optional[List[bytes]]    # Páginas como imágenes
    
    # Análisis IA
    classification: Optional[Dict]   # Tipo de documento
    summary: Optional[str]          # Resumen generado
    entities: Optional[List[Dict]]  # Entidades extraídas
    tags: Optional[List[str]]       # Tags generados
    
    # Control de flujo
    tasks_requested: List[str]      # ['classify', 'summarize', 'entities', 'tags']
    current_step: str               # Paso actual
    errors: List[str]               # Errores acumulados
    webhook_sent: bool              # Estado webhook