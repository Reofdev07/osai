import os
import puremagic
import fitz
import traceback
from tenacity import retry, stop_after_attempt, wait_exponential
from markitdown import MarkItDown
import base64

# --- Imports de tu propio proyecto ---
from app.schemas.graph_state import DocumentState
from app.schemas.agent_schemas import MegaEnrichmentOutput, ExtractionSummary
from app.utils.token_counter import count_tokens, update_usage_metadata
from app.core.config import settings
from app.core.llm import create_llm, create_llm_emergency

# --- CONFIGURACIÓN GLOBAL PARA LOS NODOS ---
CONTEXT_WINDOW_LIMIT = 300000 # ~75k tokens, suficiente para documentos largos

# === NODOS DE ENRUTAMIENTO Y DECISIÓN ===

async def analyze_and_route_node(state: DocumentState) -> dict:
    """
    Analiza el archivo y decide la ruta inicial:
    - pdf_text / office_document -> markitdown_extract
    - pdf_scanned / image -> vision_extract
    """
    file_path = state["file_path"]
    job_id = state.get("job_id", "N/A")
    
    print(f"--- Decisor: Analizando archivo para ruta óptima (Job: {job_id}) ---")
    
    try:
        mime_type = puremagic.from_file(file_path, mime=True)
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # 1. Imágenes
        if "image" in mime_type:
            print("--- Decisor: Detectada IMAGEN. Ruta: vision_extract ---")
            return {"file_type": "image", "page_count": 1}
        
        # 2. PDFs
        if "pdf" in mime_type:
            # Por defecto, enviamos a markitdown_extract para ver si tiene texto nativo
            print("--- Decisor: Detectado PDF. Ruta inicial: markitdown_extract ---")
            return {"file_type": "pdf_text"}
            
        # 3. Documentos Office y Otros (MarkItDown maneja DOCX, XLSX, CSV, TXT, HTML, etc.)
        office_extensions = ['.docx', '.xlsx', '.csv', '.ppt', '.pptx', '.doc', '.xls', '.txt', '.html', '.xml', '.json']
        if file_ext in office_extensions or any(t in mime_type for t in ['wordprocessingml', 'spreadsheetml', 'ms-excel', 'msword', 'text/plain', 'text/html']):
            print(f"--- Decisor: Detectado DOCUMENTO ({file_ext}). Ruta: markitdown_extract ---")
            return {"file_type": "office_document", "page_count": 1}
            
        # Si es algo totalmente desconocido, igual intentamos con MarkItDown por si acaso
        print(f"--- Decisor: Formato desconocido ({file_ext}), intentando extracción local. ---")
        return {"file_type": "office_document", "page_count": 1}
    except Exception as e:
        print(f"Error en analyze_and_route: {e}")
        return {"file_type": "unsupported"}

# === NUEVOS NODOS: EXTRACCIÓN INTELIGENTE V2 ===

async def markitdown_extractor_node(state: DocumentState) -> DocumentState:
    """
    Extrae texto estructurado usando MarkItDown de Microsoft.
    Soporta: PDF-texto, DOCX, XLSX, CSV, TXT, PPTX, HTML.
    Costo: $0 (100% local).
    """
    print("--- Worker: Smart Ingest con MarkItDown (Local, $0) ---")
    file_path = state["file_path"]
    job_id = state.get("job_id", "N/A")
    
    try:
        md = MarkItDown()  # Sin LLM = 100% local y gratis
        result = md.convert(file_path)
        content = result.text_content
        
        if not content or len(content.strip()) < 50:
            print(f"Job [{job_id}]: MarkItDown extrajo muy poco texto. Marcando para Vision fallback.")
            return {
                "raw_text": "",
                "extraction_method": "markitdown_empty",
                "error": "Extracción local insuficiente, requiere visión."
            }
        
        token_count = count_tokens(content)
        page_count = max(1, len(content) // 3000)
        
        print(f"Job [{job_id}]: MarkItDown OK. Chars: {len(content)}, Tokens: {token_count}")
        
        return {
            "raw_text": content,
            "page_count": page_count,
            "token_count": token_count,
            "extraction_method": "markitdown",
            "extraction_pages": page_count,
            "error": None
        }
    except Exception as e:
        print(f"Job [{job_id}]: Error en MarkItDown: {e}. Marcando para Vision fallback.")
        return {
            "raw_text": "",
            "extraction_method": "markitdown_error",
            "error": f"MarkItDown falló: {e}"
        }

VISION_PROMPT = "Extract ALL text from this document page. Preserve structure: headings, lists, tables (as markdown). Return ONLY the extracted text, no commentary."

async def _extract_pages_with_vision(llm_vision, file_path: str, job_id: str) -> tuple[str, int]:
    """Lógica compartida de extracción visual (OCR multimodal)."""
    mime_type = puremagic.from_file(file_path, mime=True)
    all_text = []
    page_count = 1
    
    if "pdf" in mime_type:
        with fitz.open(file_path) as doc:
            page_count = doc.page_count
            for i, page in enumerate(doc):
                print(f"Job [{job_id}]: Vision procesando página {i+1}/{page_count}")
                pix = page.get_pixmap(dpi=200)
                img_bytes = pix.tobytes("png")
                b64 = base64.b64encode(img_bytes).decode()
                messages = [{"role": "user", "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ]}]
                response = await llm_vision.ainvoke(messages)
                all_text.append(response.content)
    elif "image" in mime_type:
        with open(file_path, "rb") as f:
            img_bytes = f.read()
        b64 = base64.b64encode(img_bytes).decode()
        messages = [{"role": "user", "content": [
            {"type": "text", "text": VISION_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}}
        ]}]
        response = await llm_vision.ainvoke(messages)
        all_text.append(response.content)
    
    return "\n\n--- Página ---\n\n".join(all_text), page_count


async def vision_extraction_node(state: DocumentState) -> DocumentState:
    """
    Extrae texto de imágenes/PDFs escaneados con 3 niveles de fallback:
      1. Gemini 2.5 Flash (Vision primario)
      2. Qwen2.5-VL vía OpenRouter (Vision respaldo)
      3. Google Vision API OCR (Determinístico, nunca falla)
    """
    from app.core.llm import create_llm_vision, create_llm_vision_fallback
    file_path = state["file_path"]
    job_id = state.get("job_id", "N/A")
    
    # --- NIVEL 1: Gemini 2.5 Flash ---
    try:
        print(f"--- Worker: Vision Nivel 1 — Gemini 2.5 Flash ---")
        vision_llm = create_llm_vision()
        content, page_count = await _extract_pages_with_vision(vision_llm, file_path, job_id)
        token_count = count_tokens(content)
        return {
            "raw_text": content, "page_count": page_count,
            "token_count": token_count, "extraction_method": "gemini_vision",
            "extraction_pages": page_count, "error": None
        }
    except Exception as e1:
        print(f"Job [{job_id}]: ⚠️ Gemini Vision falló: {e1}")
    
    # --- NIVEL 2: Qwen2.5-VL vía OpenRouter ---
    try:
        print(f"--- Worker: Vision Nivel 2 — Qwen2.5-VL (OpenRouter) ---")
        qwen_llm = create_llm_vision_fallback()
        content, page_count = await _extract_pages_with_vision(qwen_llm, file_path, job_id)
        token_count = count_tokens(content)
        return {
            "raw_text": content, "page_count": page_count,
            "token_count": token_count, "extraction_method": "qwen_vision",
            "extraction_pages": page_count, "error": None
        }
    except Exception as e2:
        print(f"Job [{job_id}]: ⚠️ Qwen Vision falló: {e2}")
    
    # --- NIVEL 3: Google Vision API OCR (determinístico) ---
    print(f"--- Worker: Vision Nivel 3 — Google Vision API OCR (último recurso) ---")
    return await extract_with_google_vision_node(state)

# Opción OCR: Google Vision (Fallback determinístico)
async def extract_with_google_vision_node(state: DocumentState) -> DocumentState:
    """Realiza OCR tradicional como último recurso usando Google Cloud Vision."""
    print("--- Worker: Ejecutando OCR con Google Vision API (Legacy Fallback) ---")
    file_path = state["file_path"]
    job_id = state.get("job_id", "N/A")
    
    try:
        from google.cloud import vision
        client = vision.ImageAnnotatorClient()
        all_text = []
        mime_type = puremagic.from_file(file_path, mime=True)
        page_count = 0
        
        if "pdf" in mime_type:
             with fitz.open(file_path) as doc:
                page_count = len(doc)
                for page in doc:
                    pix = page.get_pixmap()
                    image_bytes = pix.tobytes("png")
                    image = vision.Image(content=image_bytes)
                    response = client.text_detection(image=image)
                    if response.text_annotations:
                        all_text.append(response.text_annotations[0].description)
        else:
            with open(file_path, "rb") as image_file:
                content = image_file.read()
            image = vision.Image(content=content)
            response = client.text_detection(image=image)
            if response.text_annotations:
                all_text.append(response.text_annotations[0].description)
            page_count = 1

        full_text = "\n\n".join(all_text)
        token_count = count_tokens(full_text)
        return {
            "raw_text": full_text, "page_count": page_count,
            "token_count": token_count, "extraction_method": "google_vision_ocr",
            "extraction_pages": page_count
        }
    except Exception as e:
        print(f"Error fatal en OCR: {e}")
        return {"error": str(e), "extraction_pages": 0}

# === NODOS DE ANÁLISIS DE CONTENIDO ===

async def summarize_and_get_subject_node(state: DocumentState) -> DocumentState:
    """Genera un resumen, tema y fecha del documento usando salida estructurada."""
    print("--- Worker: Generando Resumen, Subject y Fecha ---")
    raw_text = state.get("raw_text", "")
    job_id = state.get("job_id", "N/A")
    
    if not raw_text: return {"errors": ["No hay texto para resumir"]}
    
    llm = create_llm()
    structured_llm = llm.with_structured_output(ExtractionSummary, include_raw=True)
    
    prompt = f"""
    Analiza el siguiente texto de forma técnica y profesional:
    1. SUBJECT: [Título descriptivo máximo 10 palabras]
    2. RESUMEN: [Un párrafo máximo 150 palabras]
    3. FECHA: [Fecha del documento si se encuentra, YYYY-MM-DD]
    
    Texto:
    {raw_text[:15000]}
    """
    try:
        result = await structured_llm.ainvoke(prompt)
        data = result['parsed']
        usage = result['raw'].usage_metadata

        print(f"Job [{job_id}]: Resumen generado exitosamente.")
        return {
            "summary": data.resumen, 
            "subject": data.asunto,
            "document_date": data.fecha,
            "usage_metadata": usage
        }
    except Exception as e:
        print(f"Error resumen: {e}")
        return {"summary": "Error al generar resumen", "subject": "Documento", "errors": [str(e)]}

async def mega_analysis_node(state: DocumentState) -> DocumentState:
    """
    El motor principal. Toma el texto estructurado y extrae metadatos.
    Usa el modelo configurado con fallback.
    """
    print("--- Worker: MEGA ANALYSIS (v3.1 Response Structure) ---")
    raw_text = state.get("raw_text", "")
    summary = state.get("summary", "")
    subject = state.get("subject", "")
    job_id = state.get("job_id", "N/A")

    llm = create_llm()
    structured_llm = llm.with_structured_output(MegaEnrichmentOutput, include_raw=True)
    
    prompt = f"Analiza el documento. Tema: {subject}. Resumen: {summary}. Texto: {raw_text[:50000]}"
    
    try:
        result = await structured_llm.ainvoke(prompt)
        data = result['parsed']
        usage = result['raw'].usage_metadata
        print(f"Job [{job_id}]: Mega Analysis completado.")
        
        return {
            "intent_analysis": data.intencion.model_dump(),
            "sentiment_analysis": {
                "sentimiento": {
                    "etiqueta": data.sentimiento_urgencia.etiqueta,
                    "puntuacion": data.sentimiento_urgencia.puntuacion,
                    "justificacion": data.sentimiento_urgencia.justificacion
                },
                "urgencia": {
                    "nivel": data.sentimiento_urgencia.urgencia_nivel,
                    "justificacion": data.sentimiento_urgencia.urgencia_justificacion
                }
            },
            "classification": {
                "tipologia_documental": data.clasificacion.tipologia_documental, 
                "confianza": data.clasificacion.confianza
            },
            "tags": data.etiquetas,
            "entities": data.entidades.model_dump(),
            "priority_analysis": data.prioridad.model_dump(),
            "compliance_analysis": {
                "cumple_normativa": data.conformidad.cumple_normativa,
                "resumen": data.conformidad.resumen_ejecutivo,
                "detalles": data.conformidad.analisis_detallado
            },
            "sensitivity": {
                "level": data.sensibilidad.level,
                "contains_sensitive_data": data.sensibilidad.contains_sensitive_data,
                "detected_categories": data.sensibilidad.detected_categories,
                "justification": data.sensibilidad.justification
            },
            "usage_metadata": usage
        }
    except Exception as e:
        print(f"Job [{job_id}]: Fallback Mega Analysis por error: {e}")
        emergency_llm = create_llm_emergency()
        structured_emergency = emergency_llm.with_structured_output(MegaEnrichmentOutput, include_raw=True)
        result = await structured_emergency.ainvoke(prompt)
        data = result['parsed']
        usage = result['raw'].usage_metadata
        
        return {
            "intent_analysis": data.intencion.model_dump(),
            "sentiment_analysis": {
                "sentimiento": {
                    "etiqueta": data.sentimiento_urgencia.etiqueta,
                    "puntuacion": data.sentimiento_urgencia.puntuacion,
                    "justificacion": data.sentimiento_urgencia.justificacion
                },
                "urgencia": {
                    "nivel": data.sentimiento_urgencia.urgencia_nivel,
                    "justificacion": data.sentimiento_urgencia.urgencia_justificacion
                }
            },
            "classification": {
                "tipologia_documental": data.clasificacion.tipologia_documental, 
                "confianza": data.clasificacion.confianza
            },
            "tags": data.etiquetas,
            "entities": data.entidades.model_dump(),
            "priority_analysis": data.prioridad.model_dump(),
            "compliance_analysis": {
                "cumple_normativa": data.conformidad.cumple_normativa,
                "resumen": data.conformidad.resumen_ejecutivo,
                "detalles": data.conformidad.analisis_detallado
            },
            "sensitivity": {
                "level": data.sensibilidad.level,
                "contains_sensitive_data": data.sensibilidad.contains_sensitive_data,
                "detected_categories": data.sensibilidad.detected_categories,
                "justification": data.sensibilidad.justification
            },
            "usage_metadata": usage,
            "errors": [f"Fallback Mega Analysis por error: {e}"]
        }

async def unsupported_file_node(state: DocumentState) -> DocumentState:
    """Maneja tipos de archivo no soportados."""
    return {"error": "El tipo de archivo no está soportado actualmente."}
