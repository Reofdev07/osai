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
    print(f"Job [{job_id}]: PDF detectado como escaneado. Cambiando a modo OCR página por página.")
    
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
    print("--- Nodo: Analizando archivo para enrutamiento eficiente ---")
    
    file_path = state["file_path"]
    job_id = state["job_id"]
    step = state.get("step", "Analizando archivo")
    
    
    await notify_steps_to_laravel(
            job_id=state["job_id"],
            node_name="analyze_and_route",
            step=step
        )
    
    # Heurística: Si la primera página tiene menos de 20 caracteres, la consideramos escaneada.
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
                print(f"Job [{job_id}]: Decisión -> PDF con texto. Ruta barata.")
                return {"file_type": "pdf_text"}
            else:
                print(f"Job [{job_id}]: Decisión -> PDF escaneado. Ruta cara (OCR).")
                return {"file_type": "pdf_scanned"}
                
        except Exception as e:
            print(f"Job [{job_id}]: PDF corrupto o ilegible ({e}). Se tratará como escaneado.")
            await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="analyze_and_route",
                status="failed",
                data={"error": e},
            )
            return {"file_type": "pdf_scanned"} # Si falla, la única opción es OCR

    elif "image" in mime_type:
        print(f"Job [{job_id}]: Decisión -> Archivo de imagen simple. Ruta cara (OCR).")
        
        return {"file_type": "image"}
    else:
        print(f"Job [{job_id}]: Decisión -> Tipo de archivo no soportado.")
        return {"file_type": "unsupported"}


# --- NODO PARA LA RUTA 1: PDF CON TEXTO (BARATO) ---
async def extract_from_text_pdf_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Extrayendo texto de PDF nativo ---")
    # Este nodo ya sabe que el PDF tiene texto, así que va directo al grano.
    
    step = state.get("step", "Extrayendo texto")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_from_text_pdf_node",
                step=step
            )
    
    try:
        loader = PyMuPDFLoader(state["file_path"])
        docs = loader.load()
        page_count = len(docs)
        content = "".join([doc.page_content for doc in docs])
        token_count = count_tokens(content)
        print(f"Job [{state['job_id']}]: Costo -> Páginas: {page_count}, Tokens: {token_count}")
        return {
            "raw_text": content, 
            "page_count": page_count,
            "token_count": token_count
            }
    except Exception as e:
        await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_from_text_pdf_node",
                status="failed",
                data={"error": e},)
        return {"error": f"Error extrayendo texto de PDF: {e}"}
        
    

# --- NODO PARA LA RUTA 2: PDF ESCANEADO (CARO) ---
async def extract_from_scanned_pdf_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Realizando OCR en PDF escaneado ---")
    step = state.get("step", "Extrayendo texto")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_from_text_pdf_node",
                step=step
            )
    # Este nodo ya sabe que tiene que hacer OCR, así que no pierde tiempo.
    # Llama a la función que convierte páginas a imagen y usa Vision.
    return perform_ocr_on_pdf_pages(state["file_path"], state["job_id"])


async def extract_from_single_image_node(state: DocumentState) -> DocumentState:
    """
    Nodo para archivos de imagen únicos (JPG, PNG, etc.). Siempre tiene 1 página.
    """
    print("--- Worker: Realizando OCR en imagen simple ---")
    step = state.get("step", "Extrayendo texto")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_from_text_pdf_node",
                step=step
            )
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
            await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_from_text_pdf_node",
                status="failed",
                data={"error": response.error.message},
            )
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
        await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_from_single_image_node",
                status="failed",
                data={"error": error_message},
            )
        print(f"Job [{job_id}]: {error_message}")
        return {"error": error_message}

  
async def unsupported_file_node(state: DocumentState) -> DocumentState:
    print("--- Nodo: Archivo no soportado ---")
    # Este nodo no hace nada, solo es un final para los archivos no soportados.
    return {}


async def summarize_and_get_subject_node(state: DocumentState) -> DocumentState:
    print("---" + "Worker: Resumiendo y extrayendo asunto" + "---")
    step = state.get("step", "Resumiendo y extrayendo asunto")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="summarize_and_get_subject_node",
                step=step
            )
    
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
        await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="summarize_and_get_subject_node",
                status="failed",
                data={"error": error_message},
            )
        return {"error": error_message}
    except Exception as e:
        error_message = f"Error inesperado en el nodo de resumen: {e}"
        print(f"Job [{state['job_id']}]: {error_message}")
        await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="summarize_and_get_subject_node",
                status="failed",
                data={"error": error_message},
            )
        return {"error": error_message}
      
async def classify_document_node(state: DocumentState) -> DocumentState:
    print("---" + "Worker: Clasificando el documento" + "---")
    step = state.get("step", "Clasificando el documento")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="classify_document_node",
                step=step
            )
    
    # El contexto es el resumen y el texto original
    #context = f"Asunto: {state['subject']}\nResumen: {state['summary']}\nTexto: {state['raw_text'][:8000]}"
    
    # Extraemos información del estado
    subject = state.get("subject", "")
    summary = state.get("summary", "")
    raw_text = state.get("raw_text", "")[:8000]  # Limitar para evitar contexto muy largo
    
    prompt = f"""
    Eres un asistente experto en clasificación documental para entidades públicas en Colombia. 
    Tu tarea es analizar un documento recibido por ventanilla, email, entre otras.. y clasificarlo según su tipo documental.

    Clasifica el documento en una de las siguientes categorías comunes:
    - Factura
    - Contrato
    - Tutela
    - Derecho de Petición
    - Hoja de Vida
    - Cédula de Ciudadanía
    - Informe Técnico
    - Certificado
    - Correspondencia Oficial
    - Otro

    Solo responde con el nombre de la categoría que más se ajusta. No des explicaciones.

    ---
    ASUNTO:
    {subject}

    RESUMEN:
    {summary}

    FRAGMENTO DEL TEXTO COMPLETO:
    {raw_text}
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """
    response = llm.invoke(prompt)
    
    classification = response.content
    
    return {"classification": classification}

async def tag_document_node(state: DocumentState) -> DocumentState:
    print("---" + "Worker: Generando etiquetas" + "---")
    
    # Hacemos el nodo más robusto usando .get() para evitar KeyErrors
    classification = state.get('classification', 'N/A')
    subject = state.get('subject', 'N/A')
    summary = state.get('summary', 'N/A')
    step = state.get("step", "Generando etiquetas")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="tag_document_node",
                step=step
            )

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


async def extract_entities_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Extrayendo entidades clave del documento con contexto enriquecido ---")

    classification = state.get("classification", "Otro")
    subject = state.get("subject", "")
    summary = state.get("summary", "")
    step = state.get("step", "Extrayendo entidades clave")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_entities_node",
                step=step
            )

    prompt = f"""
    Eres un asistente experto en gestión documental en Colombia.
    Vas a analizar el texto de un documento clasificado como: **{classification}**.

    Asunto del documento: {subject}
    Resumen del documento: {summary}

    Dependiendo del tipo de documento, ajusta qué tipo de entidades debes buscar.
    Por ejemplo:
    - Si es una factura: nombres de empresas, NITs, montos, fechas, número de factura.
    - Si es un contrato: partes involucradas, objeto, fechas, códigos contractuales.
    - Si es una tutela o derecho de petición: nombres de personas, entidades, fechas, pretensiones.
    - Si es una hoja de vida: nombre completo, cédula, correo, experiencia, educación.
    - Si es un informe: título, autor, fecha, entidad emisora.

    Extrae lo siguiente si está presente:
    - personas_naturales: nombres completos de personas
    - personas_juridicas: empresas, entidades
    - fechas: en formato ISO (YYYY-MM-DD)
    - montos: cantidades de dinero (ej. "$1.200.000", "COP 5 millones")
    - codigos: radicados, facturas, contratos, etc.
    - otros: direcciones, correos, conceptos relevantes

    Devuelve solo un JSON con esta estructura:
    {{
      "personas_naturales": [],
      "personas_juridicas": [],
      "fechas": [],
      "montos": [],
      "codigos": [],
      "otros": []
    }}

    ### TEXTO DEL DOCUMENTO:
    {state['raw_text'][:8000]}
    
    NO uses bloques de código ni comillas triples. Devuelve solo el JSON sin envoltorios.
    """

    try:
        response = llm.invoke(prompt)
        cleaned_content = re.sub(r"^```(?:json)?\s*|```$", "", response.content.strip(), flags=re.IGNORECASE).strip()
        extracted_entities = json.loads(cleaned_content)

        return {
            "entities": extracted_entities
        }

    except Exception as e:
        print(f"Error extrayendo entidades: {e}")
        await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="extract_entities_node",
                status="failed",
                data={"error": f"Fallo en extracción de entidades: {e}"},
            )
        return {
            "entities": {},
            "error": f"Fallo en extracción de entidades: {e}"
        }
        

async def compliance_analysis_node(state: DocumentState) -> DocumentState:
    print("--- Nodo: Análisis de conformidad para radicación documental ---")

    classification = state.get("classification", "Otro")
    subject = state.get("subject", "")
    summary = state.get("summary", "")
    raw_text = state.get("raw_text", "")
    entities = state.get("entities", {})
    step = state.get("step", "Analizando conformidad")
    await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="compliance_analysis_node",
                step=step
            )

    criterios_radicar = """
    Criterios mínimos que debe cumplir un documento para ser aceptado para radicación:

    1. Debe contener identificación clara de las partes involucradas (personas naturales o jurídicas).
    2. Debe tener fechas visibles y válidas (fecha de emisión, radicación, vencimiento si aplica).
    3. El documento debe contener un número o código único de radicado o referencia.
    4. En documentos financieros (facturas, pagos), debe tener montos claros y moneda especificada.
    5. Debe incluir el asunto o motivo del documento.
    6. Debe estar firmado o sellado digitalmente (si aplica según el tipo de documento).
    7. El texto debe ser legible y sin errores graves que impidan su comprensión.
    8. El documento debe cumplir con la normativa de conservación y autenticidad vigente.
    """

    prompt = f"""
    Eres un experto en gestión documental y normativa colombiana para radicación de documentos.

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
      "comentarios": "Explicación detallada."
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
        await notify_steps_to_laravel(
                job_id=state["job_id"],
                node_name="compliance_analysis_node",
                status="failed",
                data={"error": f"Fallo en análisis de conformidad: {e}"},
            )
        return {
            "compliance_analysis": {},
            "error": f"Fallo en análisis de conformidad: {e}"
        }

