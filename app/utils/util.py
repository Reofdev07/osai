import tempfile
import httpx
import os
import tiktoken
import json        
import traceback
import asyncio


from urllib.parse import urlparse


from ..graphs.documents_analysis_graph import app_graph
from .notifications import notify_steps_to_laravel


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
        "mega_analysis": "Analizando globalmente (Clasificación, Entidades, Prioridad y Cumplimiento)",
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
    background_tasks = set()

    async for step in app_graph.astream(initial_state):
        
        for node_name, step_output in step.items():
            print(f"Job [{job_id}]: Progreso -> Nodo '{node_name}' completado.")
            
            # Aseguramos que step_output sea un diccionario mutable
            step_output = dict(step_output) if step_output else {}
            accumulated_state.update(step_output)

            # Lógica de notificación centralizada
            description = step_descriptions.get(node_name, f"Procesando {node_name}...")
            
            status = "processing"
            
            # Manejo de errores amigable para la UI de Laravel
            if step_output.get("error"):
                status = "failed"
                step_output.update({"user_message": f"Aviso técnico al extraer '{description}'. El documento continuará procesándose de forma segura."})
            elif step_output.get("errors") and len(step_output["errors"]) > 0:
                status = "failed"
                step_output.update({"user_message": f"Se encontraron dificultades analizando '{description}'. Los datos mostrados podrían ser parciales."})

            # Notificación en segundo plano (Fire-and-forget)
            task = asyncio.create_task(notify_steps_to_laravel(
                job_id=job_id,
                node_name=node_name,
                status=status,
                data=step_output,
                step=description
            ))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

    final_state = accumulated_state
    
    # Evaluación del estado final para enviar alertas claras
    final_status = "finished"
    final_message = "Proceso completado."
    
    if final_state.get("error") or (final_state.get("errors") and len(final_state["errors"]) > 0):
        final_status = "finished_with_errors"
        final_message = "Análisis finalizado (con datos parciales debido a formatos irregulares)."
    
    # Notificación final con el estado completo
    final_task = asyncio.create_task(notify_steps_to_laravel(
        job_id=job_id,
        node_name="graph_process",
        status=final_status,
        data=final_state,
        step=final_message
    ))
    background_tasks.add(final_task)
    final_task.add_done_callback(background_tasks.discard)

    # Esperar un tiempo razonable a que terminen las notificaciones de fondo antes de retornar
    if background_tasks:
        print(f"⏳ Job [{job_id}]: Esperando a que terminen {len(background_tasks)} notificaciones pendientes...")
        await asyncio.wait(background_tasks, timeout=3.0)

    print(f"✅ Job [{job_id}]: Proceso del grafo completado.")
    return final_state
    


# --- LÍMITE DE CONCURRENCIA PARA PROTECCIÓN DEL SERVIDOR ---
# Si entran 50 peticiones simultáneas, solo 5 se procesarán activamente a la vez.
# Las otras 45 esperarán su turno sin saturar RAM ni ancho de banda.
MAX_CONCURRENT_DOCS = 5
doc_processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOCS)

async def stream_download_file(url: str, job_id: str):
    """
      Downloads a file, SAVING IT WITH ITS CLEANED ORIGINAL EXTENSION,
      and then processes it with the graph. Limited by Semaphore.
    """
    
    print(f"🚦 Job [{job_id}]: En cola. Esperando turno de procesamiento...")
    async with doc_processing_semaphore:
        print(f"🟢 Job [{job_id}]: Turno asignado. Iniciando descarga y proceso...")
        
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
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension, prefix="osai_") as temp_file:
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