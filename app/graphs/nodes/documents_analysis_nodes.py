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
from app.utils.token_counter import count_tokens
from app.core.llm import create_llm
from app.core.config import settings
from app.core.database import DB_FILE  # Importa la ruta centralizada de la DB

# --- CONFIGURACIÓN GLOBAL PARA LOS NODOS ---
LLAMA_PARSE_FREE_LIMIT_WEEKLY = 7000
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
    print("--- Worker: Resumiendo y extrayendo asunto ---")
    if not state.get("raw_text", "").strip(): return {"error": "No hay texto para analizar."}
    prompt = f"""
    Este texto proviene de un sistema automatizado de gestión documental. El resumen y asunto se utilizarán para clasificar y visualizar documentos en una interfaz para personas usuarias. Sé claro y preciso.

    ### INSTRUCCIONES ###
    1. Resume el contenido del documento en español en un máximo de 3 a 4 oraciones.
    2. Luego, redacta un "asunto" o título corto que describa claramente de qué trata el documento.

    ### FORMATO DE RESPUESTA ###
    Devuelve solo un JSON con estas claves:
    - "resumen": string
    - "asunto": string

    ### EJEMPLO ###
    TEXTO DE ENTRADA:
    El presente documento establece los términos del contrato de arrendamiento entre Juan Pérez y María Rodríguez, sobre el apartamento ubicado en la Calle 123 de Bogotá...

    RESPUESTA:
    {{
    "resumen": "El documento es un contrato de arrendamiento entre dos partes para una propiedad ubicada en Bogotá, con una duración de 12 meses.",
    "asunto": "Contrato de Arrendamiento - Propiedad en Bogotá"
    }}

    ### TEXTO DEL DOCUMENTO ###
    {state['raw_text'][:8000]}
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.content.strip(), flags=re.DOTALL)
        data = json.loads(cleaned_content)
        return {"summary": data.get("resumen"), "subject": data.get("asunto")}
    except Exception as e:
        return {"error": f"Error en nodo de resumen: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}

async def intent_detection_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Detección de intención ---")
    contexto_analisis = f"Asunto: {state.get('subject', '')}\nResumen: {state.get('summary', '')}"
    prompt = f"""
    Eres un analista experto en trámites. Tu objetivo es identificar la acción principal que el remitente quiere que la entidad realice.

    Contexto:
    {contexto_analisis}

    Selecciona la intención principal de la siguiente lista de acciones predefinidas:
    - "Solicitar Información": El remitente pide datos, copias, o aclaraciones.
    - "Presentar Queja/Reclamo": El remitente expresa insatisfacción o denuncia un problema.
    - "Radicar para Pago": El remitente envía una factura o cuenta de cobro para ser pagada.
    - "Entregar Documentación Requerida": El remitente está respondiendo a una solicitud previa de la entidad.
    - "Iniciar Trámite Nuevo": El remitente está solicitando un permiso, licencia, o un nuevo proceso.
    - "Notificar Decisión/Resolución": Un ente externo o interno está informando de una decisión legal o administrativa.
    - "Consulta General": El remitente hace una pregunta general que no requiere una acción compleja.
    - "Informativo/Cortesía": El documento no requiere acción, es solo para mantener informada a la entidad.

    Devuelve únicamente un objeto JSON con la siguiente estructura:
    {{
      "intencion": "El nombre exacto de la intención de la lista",
      "justificacion": "Una frase corta que explique por qué elegiste esa intención, basada en el texto."
    }}
    """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.content.strip(), flags=re.DOTALL)
        data = json.loads(cleaned_content)
        return {"intent_analysis": data}
    except Exception as e:
        return {"error": f"Error en nodo de intención: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}

async def sentiment_and_urgency_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Analizando sentimiento, Intención y Prioridad ---")
    contexto_analisis = f"Asunto: {state.get('subject', '')}\nResumen: {state.get('summary', '')}\nPrimeros párrafos: {state.get('raw_text', '')[:1000]}"
    prompt = f"""
    Eres un experto en comunicación y psicología. Analiza el siguiente texto de un documento oficial.

    Contexto del Documento:
    {contexto_analisis}

    Realiza dos tareas:
    1.  **Análisis de Sentimiento:** Evalúa el tono general del remitente.
    2.  **Detección de Urgencia:** Identifica si el lenguaje sugiere una necesidad de respuesta inmediata.

    Devuelve únicamente un objeto JSON con la siguiente estructura:
    {{
      "sentimiento": {{
        "etiqueta": "Positivo | Neutro | Negativo",
        "puntuacion": "Un número de -1.0 (muy negativo) a 1.0 (muy positivo)",
        "justificacion": "Una breve explicación de por qué se asignó ese sentimiento."
      }},
      "urgencia": {{
        "nivel": "Baja | Media | Alta | Crítica",
        "justificacion": "Explica por qué el lenguaje del documento implica este nivel de urgencia."
      }}
    }}

    Ejemplo para una queja fuerte:
    {{
      "sentimiento": {{
        "etiqueta": "Negativo",
        "puntuacion": -0.8,
        "justificacion": "El remitente usa un lenguaje confrontacional y expresa frustración con el servicio."
      }},
      "urgencia": {{
        "nivel": "Alta",
        "justificacion": "El remitente menciona 'respuesta inmediata' y amenaza con acciones legales."
      }}
    }}

    NO uses bloques de código ni comillas triples. Devuelve solo el JSON.
    """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.content.strip(), flags=re.DOTALL)
        data = json.loads(cleaned_content)
        return {"sentiment_analysis": data}
    except Exception as e:
        return {"error": f"Error en nodo de sentimiento: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}

async def classify_document_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Clasificando el documento ---")
    contexto = f"""
    Asunto: {state.get("subject", "No disponible")}
    Resumen: {state.get("summary", "No disponible")}
    Intención detectada: {state.get("intent_analysis", {}).get("intencion", "No disponible")}
    Texto completo (primeros 8000 caracteres): {state.get("raw_text", "")[:8000]}
    """
    prompt = f"""
    Eres un asistente experto en gestión documental para una entidad pública colombiana. 
    Tu tarea es identificar la **tipología documental** más apropiada para el siguiente documento, basándote en una lista predefinida y en el contenido del archivo.

    ### MARCO DE REFERENCIA NORMATIVO
    La gestión documental en Colombia, según la Ley 594 de 2000, incluye procesos como la producción, recepción, trámite y organización de documentos. 
    Las **tipologías documentales** son las diferentes clases de documentos que se producen o reciben (ej: informes, contratos, solicitudes). 
    El objetivo de identificarlas correctamente es facilitar su posterior organización y aplicación de las Tablas de Retención Documental (TRD).

    ### Contexto del Documento a Analizar:
    {contexto}

    ### LISTA CERRADA DE TIPOLOGÍAS DOCUMENTALES:
    - Acto Administrativo: Documento que manifiesta una decisión de la autoridad administrativa (ej: Resolución, Decreto, Circular).
    - Contrato: Acuerdo de voluntades para crear o transmitir derechos y obligaciones.
    - Informe: Documento que expone hechos o datos verificables sobre un asunto específico.
    - Factura o Cuenta de Cobro: Documento comercial que indica una deuda por la venta de bienes o prestación de servicios.
    - Historia Laboral: Expediente que reúne los documentos relacionados con la vida laboral de un funcionario.
    - Hoja de Vida: Documento que resume la experiencia y formación de una persona.
    - Solicitud: Documento mediante el cual se realiza una petición, queja, reclamo o consulta (Derecho de Petición).
    - Tutela: Acción judicial para la protección de derechos fundamentales.
    - Comunicación Oficial: Oficios, memorandos y otras comunicaciones formales entre dependencias o entidades.
    - Póliza: Contrato de seguro.
    - Certificado: Documento que da constancia de un hecho o cualidad.
    - Otro: Documentos que no encajan claramente en ninguna de las categorías anteriores.
    
    ### Instrucciones:
    1- Analiza el contexto proporcionado del documento.
    2- Elige la tipología documental más precisa de la "LISTA CERRADA DE TIPOLOGÍAS". No puedes usar un valor que no esté en la lista.
    3- Si el documento es una queja o un reclamo, clasifícalo como "Solicitud", ya que se enmarca en el derecho de petición.
    4- Si tienes dudas o la información es ambigua, asigna "Otro" con una confianza baja (≤ 0.5).
    5- Calcula tu nivel de confianza en la clasificación, siendo un número decimal entre 0.0 y 1.0.
    6- Responde únicamente con un objeto JSON válido. No incluyas explicaciones, saludos ni texto adicional.

    ### Formato de Salida:
    {{
    "tipologia_documental": "Uno de los valores exactos de la lista",
    "confianza": 0.95
    }}
    """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.content.strip(), flags=re.DOTALL)
        data = json.loads(cleaned_content)
        return {"classification": data}
    except Exception as e:
        return {"error": f"Error en nodo de clasificación: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}

async def tag_document_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Generando etiquetas ---")
    contexto = f"""
    - El documento ha sido clasificado como: **{state.get('classification', 'N/A')}**
    - Asunto: {state.get('subject', 'N/A')}
    - Resumen: {state.get('summary', 'N/A')}
    """
    prompt = f"""
    Eres un asistente experto en análisis documental. 
    Tu tarea es generar entre 5 y 7 etiquetas únicas, claras y relevantes, basadas en el contenido de un documento.

    - Las etiquetas deben estar en español, ser palabras o frases cortas, no repetidas, y en minúsculas.
    - No uses símbolos, ni hashtags, ni explicaciones.

    Contenido:
    {contexto}

    Devuelve únicamente una lista en formato JSON válida, por ejemplo:
    ["etiqueta1", "etiqueta2", "etiqueta3", ...]
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = response.content.strip().strip("'\"")
        tags = json.loads(cleaned_content)
        return {"tags": tags}
    except Exception as e:
        return {"error": f"Error en nodo de etiquetas: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}

async def extract_entities_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Extrayendo entidades clave ---")
    contexto = f"""
    Clasificación: **{state.get("classification", "Otro")}**.
    Asunto: {state.get("subject", "")}
    Resumen: {state.get("summary", "")}
    """
    prompt = f"""
    Eres un asistente experto en gestión documental en Colombia.
    Analiza el siguiente documento, basado en su contexto.

    Contexto:
    {contexto}

    ### Instrucciones:
    1. Identifica entidades, montos, fechas, códigos y hechos relevantes.
    2. Siempre agrega una breve descripción contextual de cada dato extraído.
    3. Si es posible, organiza una línea de tiempo con los eventos principales (fecha + evento).
    4. Lista hechos relevantes aunque no tengan fecha exacta.
    5. Devuelve SOLO un JSON válido, sin texto adicional, sin bloques de código y sin comillas triples.

    ### Estructura de salida JSON:
    {{
    "personas_naturales": [
        {{"nombre": "...", "rol": "..."}}
    ],
    "personas_juridicas": [
        {{"nombre": "...", "rol": "..."}}
    ],
    "fechas": [
        {{"fecha": "YYYY-MM-DD", "descripcion": "..."}}
    ],
    "montos": [
        {{"valor": "...", "descripcion": "..."}}
    ],
    "codigos": [
        {{"codigo": "...", "descripcion": "..."}}
    ],
    "otros": [
        {{"dato": "...", "descripcion": "..."}}
    ],
    "linea_de_tiempo": [
        {{"fecha": "YYYY-MM-DD", "evento": "..."}}
    ],
    "hechos_relevantes": [
        "..."
    ]
    }}

    ### TEXTO DEL DOCUMENTO:
    {state['raw_text'][:8000]}
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.content.strip(), flags=re.DOTALL)
        data = json.loads(cleaned_content)
        # Aquí puedes agregar tu función de normalización si es necesaria
        return {"entities": data}
    except Exception as e:
        return {"error": f"Error en nodo de extracción de entidades: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}

async def priority_assignment_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Asignando Prioridad Legal y Operativa ---")
    contexto_completo = {
        "clasificacion": state.get("classification"),
        "intencion": state.get("intent_analysis", {}).get("intencion"),
        "sentimiento": state.get("sentiment_analysis", {}).get("sentimiento", {}).get("etiqueta"),
        "urgencia_tono": state.get("sentiment_analysis", {}).get("urgencia", {}).get("nivel"),
        "entidades": state.get("entities", {})
    }
    prompt = f"""
        Eres un asesor legal experto en derecho administrativo colombiano, especializado en la Ley 1755 de 2015 (Derecho de Petición). 
        Tu única tarea es analizar el siguiente documento y asignarle un nivel de prioridad y un término de respuesta legal, basándote exclusivamente en el marco normativo proporcionado.

        ### MARCO LEGAL Y TÉCNICO VINCULANTE (Ley 1755 de 2015 y CPACA)

        **Términos Generales (Artículo 14, Ley 1755):**
        1.  **Solicitud de documentos y de información:** 10 días hábiles.
        2.  **Petición de consulta a las autoridades en relación con las materias a su cargo:** 30 días hábiles.
        3.  **Cualquier otra petición (Regla General):** 15 días hábiles.

        **Atención Prioritaria (Artículo 20, Ley 1755):**
        1.  **Peticiones para evitar un perjuicio irremediable:** Se debe dar atención prioritaria. El término de respuesta sigue siendo el general.
        2.  **Peticiones de periodistas para el ejercicio de su actividad:** Se tramitará preferencialmente. El término de respuesta sigue siendo el general.

        **Peticiones entre Autoridades (Artículo 31, CPACA):**
        1.  **Solicitudes de información entre autoridades:** 10 días hábiles.

        ### CRITERIOS DE CLASIFICACIÓN (de mayor a menor)
        *   **PRIORIDAD ALTA:** Solicitud de documentos/información o entre autoridades (10 días).
        *   **PRIORIDAD MEDIA:** Petición general, quejas, reclamos (15 días).
        *   **PRIORIDAD BAJA:** Petición de consulta (30 días).

        ### DATOS DEL DOCUMENTO A EVALUAR
        {json.dumps(contexto_completo, indent=2, ensure_ascii=False)}

        ### INSTRUCCIONES ESTRICTAS
        1. Analiza el documento y determina el nivel de prioridad.
        2. Sustenta con referencia expresa a la Ley 1755 de 2015.
        3. Asigna un término de respuesta sugerido en días hábiles.
        4. Responde únicamente con un objeto JSON válido.

        ### FORMATO DE RESPUESTA OBLIGATORIO (JSON VÁLIDO ÚNICAMENTE)
        {{
        "prioridad": "Crítica | Alta | Media | Baja",
        "justificacion_legal": "Ejemplo: 'Prioridad Alta por ser petición de documentos (Art. 14, inc. 2, Ley 1755 de 2015)'",
        "termino_respuesta_sugerido_dias": 10
        }}

        RESPONDE ÚNICAMENTE CON EL JSON SOLICITADO.
        """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = re.search(r"\{.*\}", response.content, re.DOTALL).group()
        data = json.loads(cleaned_content)
        return {"priority_analysis": data}
    except Exception as e:
        return {"error": f"Error en nodo de prioridad: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}

async def compliance_analysis_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Análisis de conformidad para radicación documental ---")
    contexto = f"""
    Datos del documento:
    - Clasificación: {state.get("classification", "Otro")}
    - Asunto: {state.get("subject", "")}
    - Resumen: {state.get("summary", "")}
    - Texto (fragmento): {state.get("raw_text", "")[:6000]}
    - Entidades extraídas: {json.dumps(state.get("entities", {}), indent=2, ensure_ascii=False)}
    """
    prompt = f"""
    Eres un experto en gestión documental y archivística colombiana, especializado en el Acuerdo 060 de 2001 del AGN.
    Realiza una verificación de conformidad del documento para determinar si cumple con los requisitos mínimos para su radicación.
    
    ### CRITERIOS DE VERIFICACIÓN (Basados en la norma)
    1.  **Datos del Remitente:** ¿Identifica claramente quién envía (nombre, contacto)?
    2.  **Destinatario:** ¿Está dirigido a esta entidad?
    3.  **Asunto:** ¿Tiene un propósito claro?
    4.  **Firma y Responsable:** ¿Está firmado o presenta nombre del responsable? (Si no, es anónimo).
    5.  **Integridad y Legibilidad:** ¿Es legible y parece completo?
    6.  **Anexos:** ¿Menciona anexos?

    ###  INSTRUCCIONES ESTRICTAS:
    1- Evalúa el documento punto por punto contra los 6 "CRITERIOS DE VERIFICACIÓN".
    2- En el campo "comentarios", detalla el resultado de cada criterio.
    3- Si un criterio no cumple, explica por qué.
    4- En "cumple_normativa", pon false si alguno de los criterios 1, 2, 3 o 5 no cumple.
    5- Al final de los comentarios, añade una sección de "Recomendaciones".
    6- Responde únicamente con un objeto JSON válido.

    ### Contexto a Analizar:
    {contexto}

    Responde únicamente en JSON con esta estructura:
    {{
      "cumple_normativa": true | false,
      "comentarios": "Verificación detallada de los 6 criterios...\n\n**Recomendaciones:**\n- Si es anónimo: 'Remitir sin radicar a la oficina competente para su evaluación.'\n- Si falta asunto: 'Solicitar al remitente que aclare el motivo.'\n- Si todo está OK: 'Proceder con la radicación y registro.'"
    }}
    """
    try:
        response = await llm.ainvoke(prompt)
        cleaned_content = re.search(r"\{.*\}", response.content, re.DOTALL).group()
        data = json.loads(cleaned_content)
        return {"compliance_analysis": data}
    except Exception as e:
        return {"error": f"Error en nodo de conformidad: {e}. Respuesta: {response.content if 'response' in locals() else 'N/A'}"}