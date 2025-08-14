import tempfile
import httpx
import os
import tiktoken
import json


from  ..graphs.documents_analysis_graph import app_graph
from ..utils.notifications import notify_steps_to_laravel


#OJO ESTE PUEDE CAMBIAR A OTRO MOUDLO
# async def process_document_graph(file_path: str, job_id: str):
#     """
#     Esta función representa todo el workflow de LangGraph.
#     Recibe la ruta al archivo y hace todo el trabajo.
#     """
#     print(f"⚙️ Grafo [Job {job_id}]: Iniciando procesamiento para el archivo {file_path}")

#     initial_state = {
#         "job_id": job_id, 
#         "file_path": file_path,
#         'file_type': None,                
#         'raw_text': None,       
#         'pages': None,  
#         'classification': None,
#         'summary': None,
#         'entities': None,
#         'tags': None,
#         'tasks_requested': [],
#         'current_step': None,
#         'errors': [],
#         'webhook_sent': False
#     }

#     final_state = None
#     async for step in app_graph.astream(initial_state):
#         step_name = list(step.keys())[0]
#         print(f"Job [{job_id}]: Estado final del nodo '{step_name}' recibido.")
#         final_state = step
        
#         # await notify_steps_to_laravel(
#         #     job_id=job_id,
#         #     node_name="graph_process",
#         #     status="finished",
#         #     data=final_state
#         # )

#     print(f"Job [{job_id}]: Proceso del grafo completado. Estado final: {final_state}")
    
#     # final_state = await app_graph.ainvoke(initial_state)
    
#     # print("\n--- ✅ Grafo Finalizado ---")
#     # print("Estado final del workflow:")
#     # print(final_state)

# async def process_document_graph(file_path: str, job_id: str):
#     """
#     Función que transmite el progreso y devuelve el estado final completo.
#     """
#     print(f"⚙️ Grafo [Job {job_id}]: Iniciando procesamiento...")

#     initial_state = {
#         "job_id": job_id, 
#         "file_path": file_path,
#         'file_type': None,                
#         'raw_text': None,       
#         'pages': None,  
#         'classification': None,
#         'summary': None,
#         'sentiment_analysis': None,
#         'intent_analysis': None,
#         'priority_analysis': None,
#         'compliance_analysis': None,
#         'entities': None,
#         'tags': None,
#         'tasks_requested': [],
#         'current_step': None,
#         'errors': [],
#         'webhook_sent': False,
#         'step': None
#     }

#     # Usaremos una variable para acumular el estado
#     accumulated_state = initial_state.copy()

#     # Iteramos con astream para el progreso en tiempo real
#     async for step in app_graph.astream(initial_state):
#         step_name = list(step.keys())[0]
#         step_output = step[step_name]

#         print(f"Job [{job_id}]: Progreso -> Nodo '{step_name}' completado.")

#         # Actualizamos nuestro estado acumulado
#         accumulated_state.update(step_output)

#         # Puedes seguir notificando a Laravel aquí con el estado parcial si quieres
#         # await notify_steps_to_laravel(...)

#     # Al final del bucle, 'accumulated_state' tiene todo.
#     final_state = accumulated_state

#     print(f"✅ Job [{job_id}]: Proceso del grafo completado.")
#     print("--- ESTADO FINAL CONSOLIDADO ---")
#     print(json.dumps(final_state, indent=2, ensure_ascii=False))
#     print("---------------------------------")

#     return final_state


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

            # Lógica de notificación centralizada (ahora dentro del bucle)
            description = step_descriptions.get(node_name, f"Procesando {node_name}...")

            await notify_steps_to_laravel(
                job_id=job_id,
                node_name=node_name,
                status="failed" if "error" in step_output else "processing",
                data=step_output,
                step=description
            )

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
    

async def stream_download_file(url: str, job_id: str):
    """
      Downloads a file from a URL and saves it to a temporary location.
      Returns the path to the downloaded file.
    """
    
    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, f"{job_id}.tmp")    
    try:
      # --- PARTE 1: DESCARGA COMPLETA ---
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", str(url)) as response:
                response.raise_for_status()
                
                # Abrimos el archivo una sola vez
                with open(temp_file_path, "wb") as f:
                    # El bucle SOLO se encarga de escribir en el disco
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)
        
        # Esta línea se ejecuta DESPUÉS de que el bucle anterior haya terminado
        print(f"📥 Job [{job_id}]: Descarga completada. El archivo está listo en {temp_file_path}")

        # --- PARTE 2: PROCESAMIENTO (UNA SOLA VEZ) ---
        # Ahora que el archivo está completo, llamamos al grafo UNA vez.
        await process_document_graph(file_path=temp_file_path, job_id=job_id)

    except Exception as e:
        print(f"❌ ERROR en Job [{job_id}]: {e}")
    
    finally:
        # --- PARTE 3: LIMPIEZA (SIEMPRE AL FINAL) ---
        print(f"🧹 Limpieza [Job {job_id}]: Intentando eliminar el archivo temporal.") 
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            print(f"🗑️ Limpieza [Job {job_id}]: Archivo eliminado exitosamente.")
        else:
            print(f"🤔 Limpieza [Job {job_id}]: El archivo no se encontró para eliminar.")
               
    


 
    
    
