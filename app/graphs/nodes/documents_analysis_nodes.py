# import magic
import puremagic
import fitz
import os
import json
import re
import asyncio
import sqlite3
from datetime import datetime, timedelta

# --- Imports de librerías ---
from langchain_community.document_loaders import PyMuPDFLoader
from google.cloud import vision
from llama_parse import LlamaParse
from llama_index.core import SimpleDirectoryReader

# --- Imports de tu propio proyecto ---
from app.schemas.graph_state import DocumentState
from app.utils.token_counter import count_tokens, update_usage_metadata
from app.utils.toon_helper import get_toon_context
from app.core.llm import create_llm
from app.core.config import settings
from app.core.database import DB_FILE  # Importa la ruta centralizada de la DB
from app.schemas.agent_schemas import (
    ExtractionSummary, IntentAnalysis, SentimentUrgency, 
    ClassificationOutput, EntitiesOutput, PriorityOutput, ComplianceOutput, TagsOutput,
    MasterEnrichmentOutput
)

# --- CONFIGURACIÓN GLOBAL PARA LOS NODOS ---
LLAMA_PARSE_FREE_LIMIT_WEEKLY = 7000
CONTEXT_WINDOW_LIMIT = 300000 # ~75k tokens, suficiente para documentos largos
llm = create_llm()
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS

# === NODO 1: RUTA DE ENTRADA ===
async def analyze_and_route_node(state: DocumentState) -> DocumentState:
    """Analiza el tipo de archivo y decide la ruta inicial: texto, OCR o no soportado."""
    print("--- Nodo: Analizando tipo de archivo ---")
    file_path = state["file_path"]
    TEXT_THRESHOLD = 20
    # mime_type = magic.from_file(file_path, mime=True)
    mime_type = puremagic.from_file(file_path, mime=True)
    
    if "pdf" in mime_type:
        try:
            with fitz.open(file_path) as doc:
                if doc.page_count == 0: return {"file_type": "unsupported"}
                page = doc.load_page(0)
                text = page.get_text()
            return {"file_type": "pdf_text"} if len(text) > TEXT_THRESHOLD else {"file_type": "pdf_scanned"}
        except Exception:
            return {"file_type": "pdf_scanned"}
    elif "image" in mime_type:
        return {"file_type": "image"}
    else:
        return {"file_type": "unsupported"}

# === NODOS DE EXTRACCIÓN DE TEXTO ===

# Ruta Barata: PDF con texto nativo
async def extract_from_text_pdf_node(state: DocumentState) -> DocumentState:
    """Extrae texto directamente de un PDF nativo usando PyMuPDF."""
    print("--- Worker: Extrayendo texto de PDF nativo (ruta barata) ---")
    try:
        loader = PyMuPDFLoader(state["file_path"])
        docs = loader.load()
        content = "".join([doc.page_content for doc in docs])
        page_count = len(docs)
        token_count = count_tokens(content)
        return {"raw_text": content, "page_count": page_count, "token_count": token_count}
    except Exception as e:
        return {"error": f"Error extrayendo texto de PDF: {e}"}

# Opción OCR 1: Google Vision
async def extract_with_google_vision_node(state: DocumentState) -> DocumentState:
    """Realiza OCR usando la API de Google Cloud Vision."""
    print("--- Worker: Realizando OCR con Google Vision ---")
    file_path = state["file_path"]
    job_id = state["job_id"]
    client = vision.ImageAnnotatorClient()
    try:
        mime_type = puremagic.from_file(file_path, mime=True)
        extracted_content = ""
        page_count = 0
        if "pdf" in mime_type:
            all_text_pages = []
            with fitz.open(file_path) as doc:
                page_count = doc.page_count
                if page_count == 0: return {"error": "El PDF para OCR está vacío."}
                for i, page in enumerate(doc):
                    print(f"Job [{job_id}]: Procesando página {i+1}/{page_count} con Google Vision...")
                    pix = page.get_pixmap(dpi=300)
                    image_bytes = pix.tobytes("png")
                    image = vision.Image(content=image_bytes)
                    response = client.text_detection(image=image)
                    if response.error.message: raise Exception(f"API Error pág {i+1}: {response.error.message}")
                    if response.full_text_annotation: all_text_pages.append(response.full_text_annotation.text)
            extracted_content = "\n\n--- Nueva Página ---\n\n".join(all_text_pages)
        elif "image" in mime_type:
            page_count = 1
            print(f"Job [{job_id}]: Procesando archivo de imagen con Google Vision...")
            with open(file_path, "rb") as image_file: content_bytes = image_file.read()
            image = vision.Image(content=content_bytes)
            response = client.text_detection(image=image)
            if response.error.message: raise Exception(f"API Error: {response.error.message}")
            if response.full_text_annotation: extracted_content = response.full_text_annotation.text
        else:
            return {"error": f"Tipo de archivo no soportado para Google Vision: {mime_type}"}
        token_count = count_tokens(extracted_content)
        print(f"Job [{job_id}]: Extracción con Google Vision finalizada. Páginas: {page_count}, Tokens: {token_count}")
        return {"raw_text": extracted_content, "page_count": page_count, "token_count": token_count, "error": None}
    except Exception as e:
        error_message = f"Error inesperado en Google Vision: {e}"
        print(f"Job [{job_id}]: {error_message}")
        return {"error": error_message}

# Opción OCR 2: LlamaParse
async def extract_with_llama_parse_node(state: DocumentState) -> DocumentState:
    """
    Realiza OCR y parsing usando el método verificado de parser.load_data().
    Esta función está adaptada para funcionar de forma asíncrona dentro del grafo.
    """
    print("--- Worker: Extrayendo con LlamaParse (usando lógica verificada) ---")
    file_path = state["file_path"]
    job_id = state.get("job_id", "N/A")

    try:
        # 1. Configurar el parser como en tu script funcional.
        parser = LlamaParse(
            api_key=settings.LLAMA_CLOUD_API_KEY,
            result_type="markdown",  # Mantenemos markdown por su riqueza estructural
            verbose=True
        )

        # 2. La llamada a parser.load_data() es síncrona (bloqueante).
        # Para evitar que congele toda nuestra aplicación asíncrona, debemos
        # ejecutarla en un "executor", que es la forma correcta de manejar esto.
        loop = asyncio.get_event_loop()

        def parse_document_sync():
            # Esta es la línea clave de TU código funcional.
            print(f"Job [{job_id}]: Llamando a parser.load_data() para el archivo: {file_path}")
            documents = parser.load_data([file_path])
            return documents

        # Ejecutamos la función síncrona en un hilo separado y esperamos el resultado.
        parsed_docs = await loop.run_in_executor(None, parse_document_sync)

        # 3. Procesar el resultado para que encaje en el estado del grafo.
        if not parsed_docs:
            return {"error": "LlamaParse no devolvió ningún documento."}

        # Unimos el contenido de todos los documentos parseados.
        extracted_content = "\n\n".join([doc.get_content() for doc in parsed_docs])
        
        # Obtenemos las métricas como antes.
        page_count = parsed_docs[0].metadata.get('total_pages', 1) if parsed_docs[0].metadata else state.get("page_count_for_decision", 1)
        token_count = count_tokens(extracted_content)

        print(f"Job [{job_id}]: Extracción con LlamaParse finalizada. Páginas: {page_count}, Tokens: {token_count}")

        # 4. Devolver el diccionario para actualizar el estado del grafo.
        return {
            "raw_text": extracted_content,
            "page_count": page_count,
            "token_count": token_count,
            "error": None
        }

    except Exception as e:
        error_message = f"Error inesperado durante la extracción con LlamaParse: {e}"
        print(f"Job [{job_id}]: {error_message}")
        import traceback
        traceback.print_exc() # Imprime el traceback completo para más detalles
        return {"error": error_message}

# === NODOS DEL ORQUESTADOR ADAPTATIVO ===

async def count_pages_node(state: DocumentState) -> DocumentState:
    """Nodo rápido que cuenta las páginas de un documento para la decisión."""
    print("--- Orquestador: Contando páginas del documento ---")
    file_path = state["file_path"]
    job_id = state.get("job_id", "N/A")
    page_count = 1

    try:
        print(f"Job [{job_id}]: Contando páginas para el archivo: {file_path}")

        if not os.path.exists(file_path):
            error_msg = f"El archivo no existe en la ruta: {file_path}"
            print(f"Job [{job_id}]: ERROR - {error_msg}")
            return {"error": error_msg}

        mime_type = ""
        try:
            # La llamada de importación correcta es con guion bajo
            mime_type = puremagic.from_file(file_path, mime=True) 
        except Exception as e:
            error_msg = f"Error con la librería 'puremagic': {e}"
            print(f"Job [{job_id}]: ERROR - {error_msg}")
            return {"error": error_msg}

        if "pdf" in mime_type:
            try:
                with fitz.open(file_path) as doc:
                    page_count = doc.page_count
            except Exception as e:
                error_msg = f"Error con 'fitz' al abrir el PDF: {e}"
                print(f"Job [{job_id}]: ERROR - {error_msg}")
                return {"error": error_msg}
        
    except Exception as e:
        error_msg = f"Error inesperado en count_pages_node: {e}"
        print(f"Job [{job_id}]: ERROR - {error_msg}")
        return {"error": error_msg}

    print(f"--- Orquestador: Documento tiene {page_count} páginas ---")
    return {"page_count_for_decision": page_count}



async def adaptive_ocr_orchestrator_node(state: DocumentState) -> DocumentState:
    """Decide qué proveedor usar basándose en el contador de SQLite."""
    print("--- Orquestador Adaptativo: Tomando decisión de OCR ---")
    pages_to_process = state.get("page_count_for_decision", 1)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'llama_parse_reset_timestamp'")
        last_reset_time = datetime.fromisoformat(cursor.fetchone()[0])
        if (datetime.now() - last_reset_time) >= timedelta(days=7):
            print("--- Orquestador (SQLite): Reseteando contador semanal ---")
            cursor.execute("UPDATE settings SET value = '0' WHERE key = 'llama_parse_usage'")
            cursor.execute("UPDATE settings SET value = ? WHERE key = 'llama_parse_reset_timestamp'", (datetime.now().isoformat(),))
            conn.commit()
        cursor.execute("SELECT value FROM settings WHERE key = 'llama_parse_usage'")
        current_usage = int(cursor.fetchone()[0])
    if (current_usage + pages_to_process) <= LLAMA_PARSE_FREE_LIMIT_WEEKLY:
        provider_choice = "llama_parse"
        print(f"Límite LlamaParse OK ({current_usage + pages_to_process}/{LLAMA_PARSE_FREE_LIMIT_WEEKLY}). Seleccionando LlamaParse.")
    else:
        provider_choice = "google_vision"
        print(f"Límite LlamaParse excedido ({current_usage}/{LLAMA_PARSE_FREE_LIMIT_WEEKLY}). Usando Google Vision.")
    return {"ocr_provider": provider_choice}

async def update_llama_parse_usage_node(state: DocumentState) -> DocumentState:
    """Si se usó LlamaParse, actualiza el contador en SQLite de forma atómica."""
    pages_processed = state.get("page_count", 0)
    if pages_processed > 0:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE settings SET value = CAST(value AS INTEGER) + ? WHERE key = 'llama_parse_usage'", (pages_processed,))
            conn.commit()
            cursor.execute("SELECT value FROM settings WHERE key = 'llama_parse_usage'")
            new_total = cursor.fetchone()[0]
            print(f"--- Orquestador (SQLite): Contador de LlamaParse actualizado a {new_total} ---")
    return {}

# === Nodo Final para Archivos no Soportados ===
async def unsupported_file_node(state: DocumentState) -> DocumentState:
    print("--- Nodo: Archivo no soportado, finalizando flujo. ---")
    return {"error": "Tipo de archivo no soportado."}

# === NODOS DE ANÁLISIS DE CONTENIDO (TUS PROMPTS ORIGINALES) ===

async def summarize_and_get_subject_node(state: DocumentState) -> DocumentState:
    print("--- Worker (Expert): Resumo, Asunto y Fecha ---")
    if not state.get("raw_text", "").strip(): return {"error": "No hay texto para analizar."}
    
    prompt = f"""
    Act as a professional archivist expert in Colombian documents.
    1. Summarize the following document accurately in Spanish (3-4 sentences).
    2. Extract a clear, formal subject title.
    3. Identify the document date (the date of issuance as written in the text, e.g., 'Octubre 2025' or 'Octubre 1 de 2025'). 
    
    TEXT:
    {state['raw_text'][:CONTEXT_WINDOW_LIMIT]}
    """
    try:
        # Usamos include_raw=True para capturar la metadata de tokens
        runnable = llm.with_structured_output(ExtractionSummary, include_raw=True)
        result = await runnable.ainvoke(prompt)
        
        data = result['parsed']
        usage = result['raw'].usage_metadata
        
        return {
            "summary": data.resumen, 
            "subject": data.asunto,
            "document_date": data.fecha,
            "usage_metadata": usage # El reducer en el State se encarga de sumar
        }
    except Exception as e:
        print(f"!!! Error en summarize_and_get_subject_node: {e}")
        return {"errors": [f"Error en resumen: {e}"]}

async def master_enrichment_node(state: DocumentState) -> DocumentState:
    """
    Consolida Intención, Sentimiento/Urgencia, Clasificación y Etiquetas en UNA sola llamada.
    Mantiene la misma 'capacidad cognitiva' al usar instrucciones detalladas por sección.
    """
    print("--- Worker (Expert Master): Enriquecimiento Global (Consolidado para evitar 429) ---")
    ctx = get_toon_context(state)
    
    prompt = f"""
    Act as an expert archival analyst. Perform a multi-dimensional analysis of the document context provided.
    
    CONTEXT (TOON): {ctx}
    
    SCIENTIFIC/COGNITIVE TASKS:
    
    1. INTENT DETECTION: Identify the PRIMARY action. Options: Solicitar Información, Presentar Queja/Reclamo, Radicar para Pago, 
       Entregar Documentación, Iniciar Trámite Nuevo, Notificar Decisión, Consulta General, Informativo/Cortesía.
    
    2. SENTIMENT & URGENCY: Analyze tone (-1 to 1) and urgency (Baja, Media, Alta, Crítica).
    
    3. DOCUMENT CLASSIFICATION: Identify typology (Law 594/2000). Options: Acto Administrativo, Contrato, Informe, 
       Factura, Historia Laboral, Hoja de Vida, Solicitud (PQRS), Tutela, Comunicación Oficial, Certificado, Otro.
    
    4. TAG GENERATION: Create 5-7 relevant Spanish tags.
    
    Your output MUST be highly professional and reflect the deep analysis required for archival management in Colombia.
    """
    
    try:
        runnable = llm.with_structured_output(MasterEnrichmentOutput, include_raw=True)
        result = await runnable.ainvoke(prompt)
        
        data = result['parsed']
        usage = result['raw'].usage_metadata
        
        # Mapeamos los campos a la estructura original para no romper el State
        return {
            "intent_analysis": data.intencion.dict(),
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
            "usage_metadata": usage
        }
    except Exception as e:
        print(f"!!! Error en master_enrichment_node: {e}")
        return {"errors": [f"Error en enriquecimiento maestro: {e}"]}

async def extract_entities_node(state: DocumentState) -> DocumentState:
    print("--- Worker (Expert): Extracción de Entidades ---")
    ctx = get_toon_context(state)
    prompt = f"""
    Extract key entities from the text. 
    Instructions:
    - Identify People and Organizations.
    - Detect Dates, Amounts, and specific Codes (Radicados, Case IDs).
    - Map relevant Facts and build a Timeline.
    - IMPORTANT: If a category is not found, return an empty list []. Do NOT invent data.
    
    Context: {ctx}
    Text Segment: {state['raw_text'][:CONTEXT_WINDOW_LIMIT]}
    """
    try:
        runnable = llm.with_structured_output(EntitiesOutput, include_raw=True)
        result = await runnable.ainvoke(prompt)
        
        data = result['parsed']
        usage = result['raw'].usage_metadata

        return {
            "entities": data.dict(),
            "usage_metadata": usage
        }
    except Exception as e:
        print(f"!!! Error en extract_entities_node: {e}")
        return {"errors": [f"Error en extracción de entidades: {e}"]}

async def priority_assignment_node(state: DocumentState) -> DocumentState:
    print("--- Worker (Expert): Prioridad Legal (Ley 1755) ---")
    ctx = get_toon_context(state)
    prompt = f"""
    Act as a Legal Advisor specialized in Ley 1755/2015.
    TERMS: 
    1. Docs/Info: 10 days. 
    2. Queries/Consultas: 30 days. 
    3. General/PQRS: 15 days.
    
    CRITERIA:
    - High: Docs/Info or Authority requests (10 days).
    - Mid: General requests, complaints (15 days).
    - Low: Consultas (30 days).
    
    Context: {ctx}
    Assignment: Assign priority and MUST cite the specific article/inciso of Law 1755.
    """
    try:
        runnable = llm.with_structured_output(PriorityOutput, include_raw=True)
        result = await runnable.ainvoke(prompt)
        
        data = result['parsed']
        usage = result['raw'].usage_metadata

        return {
            "priority_analysis": data.dict(),
            "usage_metadata": usage
        }
    except Exception as e:
        print(f"!!! Error en priority_assignment_node: {e}")
        return {"errors": [f"Error en prioridad: {e}"]}

async def compliance_analysis_node(state: DocumentState) -> DocumentState:
    print("--- Worker (Expert): Conformidad Archivística (Acuerdo 060) ---")
    ctx = get_toon_context(state)
    prompt = f"""
    Act as an Archival Compliance Officer. Verify compliance based on Acuerdo 060 de 2001 (AGN).
    
    CONTEXT: {ctx}
    
    CHECKLIST:
    1. Sender Identification (Clear name/contact).
    2. Recipient correctness.
    3. Purpose/Subject clarity.
    4. Signature presence.
    5. Legibility.
    6. Annexes mentioned.
    
    TASK:
    - Provide a 'resumen_ejecutivo' that captures the essence of compliance in 2-3 sentences.
    - Provide an 'analisis_detallado' with specific recommendations for filing (radicación).
    
    Be precise, professional, and concise.
    """
    try:
        runnable = llm.with_structured_output(ComplianceOutput, include_raw=True)
        result = await runnable.ainvoke(prompt)
        
        data = result['parsed']
        usage = result['raw'].usage_metadata

        return {
            "compliance_analysis": {
                "cumple_normativa": data.cumple_normativa,
                "resumen": data.resumen_ejecutivo,
                "detalles": data.analisis_detallado
            },
            "usage_metadata": usage
        }
    except Exception as e:
        print(f"!!! Error en compliance_analysis_node: {e}")
        return {"errors": [f"Error en conformidad: {e}"]}
