import magic
import fitz
import os
import json
import re

from langchain_community.document_loaders import PyMuPDFLoader

from google.cloud import vision

from app.schemas.graph_state import DocumentState
from app.utils.token_counter import count_tokens
from app.core.llm import create_llm
from app.core.config import settings
from app.utils.notifications import notify_steps_to_laravel

# Establece la ruta del archivo de credenciales
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS


llm = create_llm()  # Importa la función de creación del LLM desde tu módulo de configuración


def perform_ocr_on_pdf_pages(file_path: str, job_id: str) -> dict:
    """
    Toma un archivo PDF, convierte cada página a imagen en memoria y ejecuta OCR en cada una.
    Esta función es para los PDF que son escaneados. Devuelve un diccionario para el estado.
    """    
    client = vision.ImageAnnotatorClient()
    all_text = []

    try:
        # Abrimos el documento con PyMuPDF (fitz)
        doc = fitz.open(file_path)
        # La métrica de costo clave: el número de páginas del PDF
        page_count = doc.page_count
        
        if page_count == 0:
            return {"error": "El PDF escaneado no tiene páginas."}

        # Itera sobre cada página del PDF
        for i, page in enumerate(doc):
            print(f"Job [{job_id}]: Procesando página {i+1}/{page_count} con OCR...")
            # Convierte la página a una imagen PNG de alta calidad en memoria
            pix = page.get_pixmap(dpi=300) # Un buen DPI es clave para la calidad del OCR
            image_bytes = pix.tobytes("png")
            
            # Llama a la API de Google Vision para esa página
            image = vision.Image(content=image_bytes)
            response = client.text_detection(image=image)
            if response.error.message:
                raise Exception(f"Google Vision API error en pág {i+1}: {response.error.message}")
            
            all_text.append(response.full_text_annotation.text)
        
        doc.close() # Cerramos el documento

        # Unimos el texto de todas las páginas
        extracted_content = "\n\n--- Nueva Página ---\n\n".join(all_text)
        token_count = count_tokens(extracted_content)

        print(f"Job [{job_id}]: Costo -> Páginas (OCR): {page_count}, Tokens: {token_count}")

        return {
            "raw_text": extracted_content,
            "page_count": page_count,
            "token_count": token_count,
            "error": None
        }

    except Exception as e:
        if 'doc' in locals() and doc:
            doc.close()
        error_message = f"Error durante el OCR página a página: {e}"
        print(f"Job [{job_id}]: {error_message}")
        return {"error": error_message}


async def analyze_and_route_node(state: DocumentState) -> DocumentState:
    """
    Nodo de entrada que analiza el archivo y determina la ruta de procesamiento exacta.
    1. Distingue entre PDF e Imagen.
    2. Si es PDF, "inspecciona" la primera página para ver si es escaneado.
    """    
    file_path = state["file_path"]
    job_id = state["job_id"]
    step = state.get("step", "Analizando archivo")
    

    TEXT_THRESHOLD = 20
    
    # Primero, usamos 'magic' para saber si es un PDF o una imagen simple
    mime_type = magic.from_file(file_path, mime=True)
    
    if "pdf" in mime_type:
        try:
            # Inspección ligera: solo abrimos el PDF para ver la primera página
            doc = fitz.open(file_path)
            if doc.page_count == 0:
                return {"error": "El PDF está vacío.", "file_type": "unsupported"}
            
            page = doc.load_page(0) # Carga solo la página 0
            text = page.get_text()  # Extrae texto solo de esa página
            doc.close() # Cierra el archivo inmediatamente
            
            if len(text) > TEXT_THRESHOLD:
                return {"file_type": "pdf_text"}
            else:
                print(f"Job [{job_id}]: Decisión -> PDF escaneado. Ruta cara (OCR).")
                return {"file_type": "pdf_scanned"}
                
        except Exception as e:
            print(f"Job [{job_id}]: PDF corrupto o ilegible ({e}). Se tratará como escaneado.")
            return {"file_type": "pdf_scanned"}

    elif "image" in mime_type:
        print(f"Job [{job_id}]: Decisión -> Archivo de imagen simple. Ruta cara (OCR).")
        
        return {"file_type": "image"}
    else:
        print(f"Job [{job_id}]: Decisión -> Tipo de archivo no soportado.")
        return {"file_type": "unsupported"}


# --- NODO PARA LA RUTA 1: PDF CON TEXTO (BARATO) ---
async def extract_from_text_pdf_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Extrayendo texto de PDF nativo ---")
    
    step = state.get("step", "Extrayendo texto")

    try:
        loader = PyMuPDFLoader(state["file_path"])
        docs = loader.load()
        page_count = len(docs)
        content = "".join([doc.page_content for doc in docs])
        token_count = count_tokens(content)
        return {
            "raw_text": content, 
            "page_count": page_count,
            "token_count": token_count
            }
    except Exception as e:

        return {"error": f"Error extrayendo texto de PDF: {e}"}
        
    

# --- NODO PARA LA RUTA 2: PDF ESCANEADO (CARO) ---
async def extract_from_scanned_pdf_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Realizando OCR en PDF escaneado ---")
    step = state.get("step", "Extrayendo texto")
    # Este nodo ya sabe que tiene que hacer OCR, así que no pierde tiempo.
    # Llama a la función que convierte páginas a imagen y usa Vision.
    return perform_ocr_on_pdf_pages(state["file_path"], state["job_id"])

async def extract_from_single_image_node(state: DocumentState) -> DocumentState:
    """
    Nodo para archivos de imagen únicos (JPG, PNG, etc.). Siempre tiene 1 página.
    """
    print("--- Worker: Realizando OCR en imagen simple ---")
    step = state.get("step", "Extrayendo texto")
    file_path = state["file_path"]
    job_id = state["job_id"]

    try:
        # Instancia el cliente de la API de Vision
        client = vision.ImageAnnotatorClient()

        # Lee el contenido binario del archivo de imagen
        with open(file_path, "rb") as image_file:
            content = image_file.read()

        image = vision.Image(content=content)
        # Llama a la API para la detección de texto
        response = client.text_detection(image=image)

        if response.error.message:
            raise Exception(f"La API de Google Vision devolvió un error: {response.error.message}")

        extracted_content = response.full_text_annotation.text
        
        # Para una imagen simple, el costo de página siempre es 1
        page_count = 1
        token_count = count_tokens(extracted_content)
        
        print(f"Job [{job_id}]: Costo -> Páginas (OCR): {page_count}, Tokens: {token_count}")

        return {
            "raw_text": extracted_content,
            "page_count": page_count,
            "token_count": token_count,
            "error": None
        }

    except Exception as e:
        error_message = f"Ocurrió un error inesperado durante el OCR de la imagen: {e}"
        print(f"Job [{job_id}]: {error_message}")
        return {"error": error_message}

async def unsupported_file_node(state: DocumentState) -> DocumentState:
    print("--- Nodo: Archivo no soportado ---")
    # Este nodo no hace nada, solo es un final para los archivos no soportados.
    return {}


# --- NODO PARA LA RUTA 1: SUMMARIZO Y EXTRACCION DE ASUNTO ---
async def summarize_and_get_subject_node(state: DocumentState) -> DocumentState:
    print("---" + "Worker: Resumiendo y extrayendo asunto" + "---")
    step = state.get("step", "Resumiendo y extrayendo asunto")
    
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
    {state['raw_text']}
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """
    
    try:
        response = llm.invoke(prompt)
        # Limpiamos la respuesta del LLM: quitamos espacios y comillas simples/dobles que la envuelven
        print(response.content)
        cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        parsed_response = json.loads(cleaned_content)

        return {
            "summary": parsed_response.get("resumen"), 
            "subject": parsed_response.get("asunto")
        }
    except json.JSONDecodeError as e:
        error_message = f"Error al decodificar el JSON del LLM: {e}. Respuesta recibida: '{response.content}'"
        print(f"Job [{state['job_id']}]: {error_message}")
        # await notify_steps_to_laravel(
        #         job_id=state["job_id"],
        #         node_name="summarize_and_get_subject_node",
        #         status="failed",
        #         data={"error": error_message},
        #     )
        return {"error": error_message}
    except Exception as e:
        error_message = f"Error inesperado en el nodo de resumen: {e}"
        print(f"Job [{state['job_id']}]: {error_message}")
        # await notify_steps_to_laravel(
        #         job_id=state["job_id"],
        #         node_name="summarize_and_get_subject_node",
        #         status="failed",
        #         data={"error": error_message},
        #     )
        return {"error": error_message}


  
# --- NODO PARA ANALSIS DE SENTIMIENTOS Y DETECCION DE URGENCIAS ---
async def sentiment_and_urgency_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Analizando sentimiento, Intención y Prioridad ---")
    step = state.get("step", "Analizando Sentimiento, Intención y Prioridad")

    # Usamos el resumen y el inicio del texto para un análisis rápido y barato
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
        response = llm.invoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        analysis_result = json.loads(cleaned_content)
        return {"sentiment_analysis": analysis_result}
    except Exception as e:
        # Gestionar error
        return {"error": f"Fallo en análisis de sentimiento: {e}"}
  

# ----DETECCION DE INTENCION PRINCIPAL---------
async def intent_detection_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Detección de intención ---")
    step = state.get("step", "Detección de intención")

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
        response = llm.invoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        analysis_result = json.loads(cleaned_content)
        return {"intent_analysis": analysis_result}
    except Exception as e:
        return {"error": f"Fallo en detección de intención: {e}"}


# --- NODO PARA LA RUTA 1: CLASIFICACION, ETIQUETAS Y EXTRACCION DE ENTIDADES ---    
async def classify_document_node(state: DocumentState) -> DocumentState:
    print("---" + "Worker: Clasificando el documento" + "---")
    step = state.get("step", "Clasificando el documento")

    # Extraemos información del estado
    subject = state.get("subject", "No disponible")
    summary = state.get("summary", "No disponible")
    intent_analysis = state.get("intent_analysis")
    intencion_detectada = intent_analysis.get("intencion", "No disponible")
    raw_text = state.get("raw_text", "")[:8000]  # Limitar para evitar contexto muy largo
    
    prompt = f"""
    Eres un asistente experto en gestión documental para una entidad pública colombiana. 
    Tu tarea es identificar la **tipología documental** más apropiada para el siguiente documento, basándote en una lista predefinida y en el contenido del archivo.

    ### MARCO DE REFERENCIA NORMATIVO

    La gestión documental en Colombia, según la Ley 594 de 2000, incluye procesos como la producción, recepción, trámite y organización de documentos. 
    Las **tipologías documentales** son las diferentes clases de documentos que se producen o reciben (ej: informes, contratos, solicitudes). 
    El objetivo de identificarlas correctamente es facilitar su posterior organización y aplicación de las Tablas de Retención Documental (TRD).

    ### Contexto del Documento a Analizar:
    Asunto: {subject}
    Resumen: {summary}
    Intención detectada: {intencion_detectada}
    Texto completo (primeros 8000 caracteres): {raw_text}

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
        response = llm.invoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        classification = json.loads(cleaned_content)
        return {"classification": classification}
    except json.JSONDecodeError as e:
        error_message = f"Error al decodificar el JSON del LLM: {e}. Respuesta recibida: '{response.content}'"
        print(f"Job [{state['job_id']}]: {error_message}")

        return {"error": error_message}
    except Exception as e:
        error_message = f"Error inesperado en el nodo de clasificación: {e}"
        print(f"Job [{state['job_id']}]: {error_message}")
        return {"error": error_message} 



# --- NODO PARA LA RUTA 2: EXTRACCION DE ETIQUETAS ---
async def tag_document_node(state: DocumentState) -> DocumentState:
    print("---" + "Worker: Generando etiquetas" + "---")
    
    # Hacemos el nodo más robusto usando .get() para evitar KeyErrors
    classification = state.get('classification', 'N/A')
    subject = state.get('subject', 'N/A')
    summary = state.get('summary', 'N/A')
    step = state.get("step", "Generando etiquetas")
 
    prompt = f"""
    Eres un asistente experto en análisis documental. 
    Tu tarea es generar entre 5 y 7 etiquetas únicas, claras y relevantes, basadas en el contenido de un documento.

    - El documento ha sido clasificado como: **{classification}**
    - El objetivo es extraer conceptos clave que ayuden a identificar, buscar o agrupar este documento.
    - Las etiquetas deben estar en español, ser palabras o frases cortas, no repetidas, y en minúsculas.
    - No uses símbolos, ni hashtags, ni explicaciones.

    Contenido:
    Asunto: {subject}
    Resumen: {summary}

    Devuelve únicamente una lista en formato JSON válida, por ejemplo:
    ["etiqueta1", "etiqueta2", "etiqueta3", ...]
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """
    response = llm.invoke(prompt)
    try:
        # Limpiamos la respuesta por si viene con comillas o espacios extra
        cleaned_content = response.content.strip().strip("'" ).strip('"')
        tags = json.loads(cleaned_content)
    except json.JSONDecodeError:
        # Si falla el JSON, creamos etiquetas a partir del texto plano
        await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="tag_document_node",
                status="failed",
                data={"error": "Error al decodificar JSON"},
            )
        tags = [tag.strip() for tag in response.content.split(',')]

    return {"tags": tags}


def normalize_entities(data):
    def normalize_list(items, keys):
        normalized = []
        for item in items:
            if isinstance(item, str):
                normalized.append({keys[0]: item, keys[1]: None})
            elif isinstance(item, dict):
                normalized.append(item)
        return normalized

    data["montos"] = normalize_list(data.get("montos", []), ["valor", "descripcion"])
    data["fechas"] = normalize_list(data.get("fechas", []), ["fecha", "descripcion"])
    data["codigos"] = normalize_list(data.get("codigos", []), ["codigo", "descripcion"])
    data["otros"] = normalize_list(data.get("otros", []), ["dato", "descripcion"])
    return data

# --- NODO PARA LA RUTA 3: EXTRACCION DE ENTIDADES ---
async def extract_entities_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Extrayendo entidades clave del documento con contexto enriquecido ---")

    classification = state.get("classification", "Otro")
    subject = state.get("subject", "")
    summary = state.get("summary", "")
    step = state.get("step", "Extrayendo entidades clave")
  
    # prompt = f"""
    # Eres un asistente experto en gestión documental en Colombia.
    # Vas a analizar el texto de un documento clasificado como: **{classification}**.

    # Asunto del documento: {subject}
    # Resumen del documento: {summary}

    # Dependiendo del tipo de documento, ajusta qué tipo de entidades debes buscar.
    # Por ejemplo:
    # - Si es una factura: nombres de empresas, NITs, montos, fechas, número de factura.
    # - Si es un contrato: partes involucradas, objeto, fechas, códigos contractuales.
    # - Si es una tutela o derecho de petición: nombres de personas, entidades, fechas, pretensiones.
    # - Si es una hoja de vida: nombre completo, cédula, correo, experiencia, educación.
    # - Si es un informe: título, autor, fecha, entidad emisora.

    # Extrae lo siguiente si está presente:
    # - personas_naturales: nombres completos de personas
    # - Remitente: nombre completo
    # - Destinatario: nombre completo
    
    # - personas_juridicas: empresas, entidades
    # - fechas: en formato ISO (YYYY-MM-DD)
    # - montos: cantidades de dinero (ej. "$1.200.000", "COP 5 millones")
    # - codigos: radicados, facturas, contratos, etc.
    # - otros: direcciones, correos, conceptos relevantes

    # Devuelve solo un JSON con esta estructura:
    # {{
    #   "personas_naturales": [],
    #   "personas_juridicas": [],
    #   "fechas": [],
    #   "montos": [],
    #   "codigos": [],
    #   "otros": []
    # }}

    # ### TEXTO DEL DOCUMENTO:
    # {state['raw_text'][:8000]}
    
    # NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    # """
    prompt = f"""
    Eres un asistente experto en gestión documental en Colombia.
    Analiza el siguiente documento, clasificado como: **{classification}**.

    Asunto: {subject}
    Resumen: {summary}

    ### Instrucciones:
    1. Identifica entidades, montos, fechas, códigos y hechos relevantes.
    2. Siempre agrega una breve descripción contextual de cada dato extraído.
    - Ejemplo: en montos indicar si es subtotal, IVA, total, multa, reintegro, etc.
    - En fechas indicar si corresponde a emisión, vencimiento, firma, radicación, etc.
    - En personas o entidades indicar su rol (remitente, destinatario, empresa emisora, etc.).
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
        # response = llm.invoke(prompt)
        # cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        # extracted_entities = json.loads(cleaned_content)
        response = llm.invoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        extracted_entities = json.loads(cleaned_content)
        extracted_entities = normalize_entities(extracted_entities)

        return {
            "entities": extracted_entities
        }

    except Exception as e:
        print(f"Error extrayendo entidades: {e}")
        return {
            "entities": {},
            "error": f"Fallo en extracción de entidades: {e}"
        }
    
    
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
        1.  **Peticiones para evitar un perjuicio irremediable:** Se debe dar atención prioritaria si el peticionario prueba la titularidad de un derecho fundamental y el riesgo. 
        Medidas de urgencia se deben tomar de inmediato si está en peligro la vida o integridad. El término de respuesta sigue siendo el general (10, 15 o 30 días) pero su trámite interno debe ser preferencial.
        2.  **Peticiones de periodistas para el ejercicio de su actividad:** Se tramitará preferencialmente. El término de respuesta sigue siendo el general.

        **Peticiones entre Autoridades (Artículo 31, CPACA):**
        1.  **Solicitudes de información entre autoridades:** 10 días hábiles.

        ### CRITERIOS DE CLASIFICACIÓN (de mayor a menor)

        *   **PRIORIDAD ALTA:**
            *   Se identifica claramente como una **solicitud de documentos o de información**.
            *   Se identifica como una **petición entre autoridades**.
            *   **Justificación:** Se aplica el término legal de 10 días hábiles.

        *   **PRIORIDAD MEDIA:**
            *   Corresponde a una **petición general** que no es ni solicitud de información ni consulta.
            *   Incluye quejas, reclamos, solicitudes de reconocimiento de un derecho, etc.
            *   **Justificación:** Se aplica el término legal de 15 días hábiles.

        *   **PRIORIDAD BAJA:**
            *   Se identifica claramente como una **petición de consulta** (se pide un concepto o parecer sobre una materia a cargo de la entidad).
            *   **Justificación:** Se aplica el término legal de 30 días hábiles.

        **NOTA SOBRE LA ATENCIÓN PRIORITARIA (Art. 20):** La ley no establece un término de respuesta *diferente* para estas peticiones, solo que su *trámite* debe ser preferencial. 
        Por lo tanto, una petición de un periodista que solicita información se clasifica como "PRIORIDAD ALTA" con un término de 10 días, pero se debe señalar su carácter preferencial en la justificación.

        ### DATOS DEL DOCUMENTO A EVALUAR
        {json.dumps(contexto_completo, indent=2, ensure_ascii=False)}

        ### INSTRUCCIONES ESTRICTAS
        1. Analiza el documento y determina el nivel de prioridad.
        2. Sustenta la decisión con **referencia expresa** al artículo y la Ley 1755 de 2015.
        3. Asigna un **término de respuesta sugerido** en días hábiles.
        4. NO incluyas explicaciones fuera del JSON.
        5. Si no encuentras información suficiente, elige el nivel más bajo posible y justifica.

        ### FORMATO DE RESPUESTA OBLIGATORIO (JSON VÁLIDO ÚNICAMENTE)
        {{
        "prioridad": "Crítica | Alta | Media | Baja",
        "justificacion_legal": "Ejemplo: 'Prioridad Alta por ser petición de documentos (Art. 14, inc. 2, Ley 1755 de 2015)'",
        "termino_respuesta_sugerido_dias": 10
        }}

        RESPONDE ÚNICAMENTE CON EL JSON SOLICITADO.
        """


    try:
        response = llm.invoke(prompt)
        raw_content = response.content.strip()

        # Si el LLM envía texto adicional, intenta extraer solo el JSON
        json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if not json_match:
            return {"error": f"Respuesta no contiene JSON válido: {raw_content}"}

        cleaned_content = json_match.group()

        try:
            analysis_result = json.loads(cleaned_content)
        except json.JSONDecodeError as e:
            return {"error": f"JSON inválido: {e}. Respuesta: {cleaned_content}"}

        return {"priority_analysis": analysis_result}

    except Exception as e:
        return {"error": f"Fallo en asignación de prioridad: {e}"}



# --- NODO PARA LA RUTA 4: ANÁLISIS DE CONFORMIDAD ---
async def compliance_analysis_node(state: DocumentState) -> DocumentState:
    print("--- Nodo: Análisis de conformidad para radicación documental ---")

    classification = state.get("classification", "Otro")
    subject = state.get("subject", "")
    summary = state.get("summary", "")
    raw_text = state.get("raw_text", "")
    entities = state.get("entities", {})
    step = state.get("step", "Analizando conformidad")


    criterios_radicar = """
    Eres un experto en gestión documental y archivística colombiana, especializado en el Acuerdo 060 de 2001 del Archivo General de la Nación.
    Tu tarea es realizar una verificación de conformidad de un documento para determinar si cumple con los requisitos mínimos para su radicación
    
    ### MARCO NORMATIVO DE REFERENCIA (Acuerdo 060 de 2001)
        - **ARTÍCULO DÉCIMO:** Las comunicaciones deben ser revisadas para verificar la competencia de la entidad, los anexos, el destino, y los datos de origen (remitente, dirección, asunto).
        - **PARÁGRAFO (ART. DÉCIMO):** Las comunicaciones anónimas (sin firma ni nombre del responsable) deben ser remitidas sin radicar a la oficina competente para que determinen las acciones a seguir.
        - **ARTÍCULO SEGUNDO (Definición de Documento Original):** Debe poseer rasgos que garanticen su autenticidad e integridad.
        - **ARTÍCULO NOVENO (Conservación):** El soporte y las tintas deben garantizar permanencia y durabilidad.
        
        
    ### CRITERIOS DE VERIFICACIÓN PARA RADICACIÓN (Basados en la norma)
        1.  **Datos del Remitente:** ¿El documento identifica claramente quién lo envía (nombre de persona/entidad y datos de contacto como dirección o email)?
        2.  **Destinatario:** ¿El documento está dirigido a esta entidad o a un funcionario de la misma?
        3.  **Asunto:** ¿El documento tiene un asunto o motivo claro que permita entender su propósito?
        4.  **Firma y Responsable:** ¿El documento está firmado o presenta el nombre del responsable? (Según el Art. 10, si no lo tiene, se considera anónimo y su tratamiento es especial).
        5.  **Integridad y Legibilidad:** ¿El texto es legible y el documento parece completo, sin alteraciones evidentes?
        6.  **Anexos:** ¿Si se mencionan anexos, hay indicios de que están presentes? (La IA no puede verlos, pero puede inferir del texto).
        
    ###  INSTRUCCIONES ESTRICTAS:
        1- Evalúa el documento punto por punto contra los 6 "CRITERIOS DE VERIFICACIÓN".
        2- En el campo "comentarios", detalla el resultado de cada criterio (ej: "1. Datos del Remitente: Cumple. Se identifica a 'Juan Pérez' con email y teléfono.").
        3- Si un criterio no cumple, explica claramente por qué (ej: "4. Firma y Responsable: No Cumple. El documento no presenta firma ni nombre del remitente, se considera anónimo.").
        4- En el campo "cumple_normativa", pon false si alguno de los criterios 1, 2, 3 o 5 no cumple. El criterio de la firma (4) es especial y no necesariamente impide la radicación, pero debe ser señalado.
        5- Al final de los comentarios, añade una sección de "Recomendaciones" con las acciones a seguir.
        6- Responde únicamente con un objeto JSON válido.
    
    """

    prompt = f"""

    Evalúa el siguiente documento según estos criterios mínimos para aceptar la radicación:

    {criterios_radicar}

    Datos del documento:
    - Clasificación: {classification}
    - Asunto: {subject}
    - Resumen: {summary}
    - Texto (fragmento): {raw_text[:6000]}
    - Entidades extraídas: {json.dumps(entities, indent=2, ensure_ascii=False)}

    Indica si el documento cumple con los criterios. Si no, explica qué falta o está mal y da recomendaciones para corregirlo.

    Responde únicamente en JSON con esta estructura:
    {{
      "cumple_normativa": true | false,
    "comentarios": "Verificación detallada de los 6 criterios...
    \n\n**Recomendaciones:**
    \n- Si es anónimo: 'Remitir sin radicar a la oficina competente para su evaluación.'
    \n- Si falta el asunto: 'Solicitar al remitente que aclare el motivo de su comunicación.'
    \n- Si todo está OK: 'Proceder con la radicación y registro del documento.'"
    }}
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """

    try:
        response = llm.invoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        compliance_result = json.loads(cleaned_content)

        return {
            "compliance_analysis": compliance_result
        }

    except Exception as e:
        print(f"Error en análisis de conformidad: {e}")
        return {
            "compliance_analysis": {},
            "error": f"Fallo en análisis de conformidad: {e}"
        }

