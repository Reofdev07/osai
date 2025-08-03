import magic
import fitz
import os

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_google_community.vision import CloudVisionLoader
from langchain_core.documents import Document

from google.cloud import vision
from google.api_core import exceptions as google_exceptions

from app.schemas.graph_state import DocumentState
from app.utils.token_counter import count_tokens

from app.core.config import settings

# Establece la ruta del archivo de credenciales
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.GOOGLE_APPLICATION_CREDENTIALS


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



def analyze_and_route_node(state: DocumentState) -> DocumentState:
    """
    Nodo de entrada que analiza el archivo y determina la ruta de procesamiento exacta.
    1. Distingue entre PDF e Imagen.
    2. Si es PDF, "inspecciona" la primera página para ver si es escaneado.
    """
    print("--- Nodo: Analizando archivo para enrutamiento eficiente ---")
    
    file_path = state["file_path"]
    job_id = state["job_id"]
    
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
            return {"file_type": "pdf_scanned"} # Si falla, la única opción es OCR

    elif "image" in mime_type:
        print(f"Job [{job_id}]: Decisión -> Archivo de imagen simple. Ruta cara (OCR).")
        return {"file_type": "image"}
    else:
        print(f"Job [{job_id}]: Decisión -> Tipo de archivo no soportado.")
        return {"file_type": "unsupported"}


# --- NODO PARA LA RUTA 1: PDF CON TEXTO (BARATO) ---
def extract_from_text_pdf_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Extrayendo texto de PDF nativo ---")
    # Este nodo ya sabe que el PDF tiene texto, así que va directo al grano.
    try:
        loader = PyMuPDFLoader(state["file_path"])
        docs = loader.load()
        page_count = len(docs)
        content = "".join([doc.page_content for doc in docs])
        token_count = count_tokens(content)
        print(f"Job [{state['job_id']}]: Costo -> Páginas: {page_count}, Tokens: {token_count}")
        return {"raw_text": content, "page_count": page_count, "token_count": token_count}
    except Exception as e:
        return {"error": f"Error extrayendo texto de PDF: {e}"}
    

# --- NODO PARA LA RUTA 2: PDF ESCANEADO (CARO) ---
def extract_from_scanned_pdf_node(state: DocumentState) -> DocumentState:
    print("--- Worker: Realizando OCR en PDF escaneado ---")
    # Este nodo ya sabe que tiene que hacer OCR, así que no pierde tiempo.
    # Llama a la función que convierte páginas a imagen y usa Vision.
    return perform_ocr_on_pdf_pages(state["file_path"], state["job_id"])


def extract_from_single_image_node(state: DocumentState) -> DocumentState:
    """
    Nodo para archivos de imagen únicos (JPG, PNG, etc.). Siempre tiene 1 página.
    """
    print("--- Worker: Realizando OCR en imagen simple ---")
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



    
def unsupported_file_node(state: DocumentState) -> DocumentState:
    print("--- Nodo: Archivo no soportado ---")
    # Este nodo no hace nada, solo es un final para los archivos no soportados.
    return {}
