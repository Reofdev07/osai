from fastapi import APIRouter, File, UploadFile, HTTPException

from typing import List

# Crear el router
doc_analyze_router = APIRouter(
    prefix="/documents",
    tags=["Document Analysis"],
)

@doc_analyze_router.post("/analyze",)
async def analyze_document(files: List[UploadFile] = File(...),):
    """
    Analiza uno o múltiples documentos realizando tareas de procesamiento con IA:
    
    - **Clasificación**: Determina el tipo/categoría del documento
    - **Resumen**: Genera un resumen del contenido
    - **Etiquetado**: Extrae tags relevantes
    - **Extracción de entidades**: Identifica personas, lugares, organizaciones, etc.
    - **Metadata**: Extrae información adicional del documento
    
    Args:
        files: Uno o más archivos a analizar (PDF, DOCX, TXT, etc.)
        include_classification: Incluir clasificación del documento
        include_summary: Incluir resumen del contenido
        include_tagging: Incluir etiquetas/tags
        include_entities: Incluir extracción de entidades
        summary_length: Longitud del resumen (short, medium, long)
        language: Idioma del documento (auto, es, en, etc.)
    
    Returns:
        List[DocumentAnalysisResponse]: Lista con los resultados del análisis de cada documento
    """
    return {"message": "Document analysis is not yet implemented."}