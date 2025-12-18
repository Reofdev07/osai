import tempfile
import httpx
import os
import tiktoken
import json        
import traceback
import asyncio


from urllib.parse import urlparse


from  ..graphs.documents_analysis_graph import app_graph
from ..utils.notifications import notify_steps_to_laravel


# En tu archivo principal (donde llamas al grafo)

async def process_document_graph(file_path: str, job_id: str):
    """
    Función que transmite el progreso a Laravel de forma centralizada
    y devuelve el estado final completo.
    """
    print(f"⚙️ Grafo [Job {job_id}]: Iniciando procesamiento...")

    initial_state = { "job_id": job_id, "file_path": file_path }

    step_descriptions = {
        "__start__": "Iniciando análisis...",
        "analyze_and_route": "Analizando tipo de archivo",
        "text_pdf": "Extrayendo texto",
        "scanned_pdf": "Procesando con OCR",
        "image": "Procesando imagen con OCR",
        "summarize": "Resumiendo y extrayendo asunto",
        "intent_detection_node": "Detectando intención",
        "sentiment_and_urgency_node": "Analizando tono y urgencia",
        "classify": "Clasificando documento",
        "tag": "Generando etiquetas",
        "extract_entities": "Extrayendo entidades",
        "priority_analysis": "Asignando prioridad legal",
        "analyze_compliance": "Verificando conformidad",
        "__end__": "Análisis finalizado",
        "unsupported": "Archivo no soportado"
    }

    accumulated_state = initial_state.copy()

    async for step in app_graph.astream(initial_state):
        
        for node_name, step_output in step.items():
            print(f"Job [{job_id}]: Progreso -> Nodo '{node_name}' completado.")
            
            # Aseguramos que step_output sea un diccionario para el update
            step_output = step_output or {}
            accumulated_state.update(step_output)

            # Lógica de notificación centralizada
            description = step_descriptions.get(node_name, f"Procesando {node_name}...")

            await notify_steps_to_laravel(
                job_id=job_id,
                node_name=node_name,
                status="failed" if "error" in step_output else "processing",
                data=step_output,
                step=description
            )

            # Pequeño delay para respetar Rate Limits de Gemini Free (15 RPM)
            # Solo aplicamos el delay si el nodo es de análisis (IA)
            if node_name in ["summarize", "intent_detection", "sentiment_and_urgency", "classify", "tag", "extract_entities", "priority_assignment"]:
                await asyncio.sleep(2.5) 

    final_state = accumulated_state
    
    # Notificación final con el estado completo
    await notify_steps_to_laravel(
        job_id=job_id,
        node_name="graph_process",
        status="finished",
        data=final_state,
        step="Proceso completado."
    )

    print(f"✅ Job [{job_id}]: Proceso del grafo completado.")
    print("--- ESTADO FINAL CONSOLIDADO ---")
    print(json.dumps(final_state, indent=2, ensure_ascii=False))
    print("---------------------------------")

    return final_state
    

# async def stream_download_file(url: str, job_id: str):
#     """
#       Downloads a file from a URL and saves it to a temporary location.
#       Returns the path to the downloaded file.
#     """
    
#     temp_dir = tempfile.gettempdir()
#     temp_file_path = os.path.join(temp_dir, f"{job_id}.tmp")    
#     try:
#       # --- PARTE 1: DESCARGA COMPLETA ---
#         async with httpx.AsyncClient() as client:
#             async with client.stream("GET", str(url)) as response:
#                 response.raise_for_status()
                
#                 # Abrimos el archivo una sola vez
#                 with open(temp_file_path, "wb") as f:
#                     # El bucle SOLO se encarga de escribir en el disco
#                     async for chunk in response.aiter_bytes():
#                         f.write(chunk)
        
#         # Esta línea se ejecuta DESPUÉS de que el bucle anterior haya terminado
#         print(f"📥 Job [{job_id}]: Descarga completada. El archivo está listo en {temp_file_path}")

#         # --- PARTE 2: PROCESAMIENTO (UNA SOLA VEZ) ---
#         # Ahora que el archivo está completo, llamamos al grafo UNA vez.
#         await process_document_graph(file_path=temp_file_path, job_id=job_id)

#     except Exception as e:
#         print(f"❌ ERROR en Job [{job_id}]: {e}")
    
#     finally:
#         # --- PARTE 3: LIMPIEZA (SIEMPRE AL FINAL) ---
#         print(f"🧹 Limpieza [Job {job_id}]: Intentando eliminar el archivo temporal.") 
#         if os.path.exists(temp_file_path):
#             os.remove(temp_file_path)
#             print(f"🗑️ Limpieza [Job {job_id}]: Archivo eliminado exitosamente.")
#         else:
#             print(f"🤔 Limpieza [Job {job_id}]: El archivo no se encontró para eliminar.")
               
# Asegúrate de tener este import al principio de tu archivo

async def stream_download_file(url: str, job_id: str):
    """
      Downloads a file, SAVING IT WITH ITS CLEANED ORIGINAL EXTENSION,
      and then processes it with the graph.
    """
    
    temp_file_path = None
    
    try:

        # --- PARTE 1: DETERMINAR LA EXTENSIÓN LIMPIA Y PREPARAR LA RUTA ---
        
        try:
            # 1. Parsear la URL para separar sus componentes.
            parsed_url = urlparse(str(url))
            
            # 2. Obtener solo la RUTA de la URL, ignorando los parámetros de consulta.
            #    Ej: '/uploads/mi_contrato.pdf'
            clean_path = parsed_url.path
            
            # 3. Extraer la extensión del nombre de archivo limpio.
            _, file_extension = os.path.splitext(os.path.basename(clean_path))
            
            if not file_extension:
                raise ValueError("La ruta de la URL no contiene una extensión de archivo válida.")
        
        except ValueError as e:
            print(f"❌ ERROR [Job {job_id}]: {e}. Abortando.")
            return

        # Crear una ruta de archivo temporal SEGURA y CON la extensión correcta.
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file_path = temp_file.name

        print(f"📥 Job [{job_id}]: Se usará el archivo temporal: {temp_file_path}")

        # --- PARTE 2: DESCARGA COMPLETA (sin cambios) ---
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", str(url), follow_redirects=True, timeout=60.0) as response:
                response.raise_for_status()
                
                with open(temp_file_path, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
        
        print(f"📥 Job [{job_id}]: Descarga completada. El archivo está listo en {temp_file_path}")

        # --- PARTE 3: PROCESAMIENTO (sin cambios) ---
        await process_document_graph(file_path=temp_file_path, job_id=job_id)

    except Exception as e:
        print(f"❌ ERROR en Job [{job_id}]: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # --- PARTE 4: LIMPIEZA (sin cambios) ---
        print(f"🧹 Limpieza [Job {job_id}]: Intentando eliminar el archivo temporal.") 
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            print(f"🗑️ Limpieza [Job {job_id}]: Archivo eliminado exitosamente.")
        else:
            print(f"🤔 Limpieza [Job {job_id}]: El archivo no se encontró para eliminar o nunca se creó.")