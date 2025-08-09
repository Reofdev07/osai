import tempfile
import httpx
import os
import tiktoken


from  ..graphs.documents_analysis_graph import app_graph
from ..utils.notifications import notify_steps_to_laravel


#OJO ESTE PUEDE CAMBIAR A OTRO MOUDLO
async def process_document_graph(file_path: str, job_id: str):
    """
    Esta función representa todo el workflow de LangGraph.
    Recibe la ruta al archivo y hace todo el trabajo.
    """
    print(f"⚙️ Grafo [Job {job_id}]: Iniciando procesamiento para el archivo {file_path}")

    initial_state = {
        "job_id": job_id, 
        "file_path": file_path,
        'file_type': None,                
        'raw_text': None,       
        'pages': None,  
        'classification': None,
        'summary': None,
        'entities': None,
        'tags': None,
        'tasks_requested': [],
        'current_step': None,
        'errors': [],
        'webhook_sent': False
    }

    final_state = None
    async for step in app_graph.astream(initial_state):
        step_name = list(step.keys())[0]
        print(f"Job [{job_id}]: Estado final del nodo '{step_name}' recibido.")
        final_state = step
        
        # await notify_steps_to_laravel(
        #     job_id=job_id,
        #     node_name="graph_process",
        #     status="finished",
        #     data=final_state
        # )

    print(f"Job [{job_id}]: Proceso del grafo completado. Estado final: {final_state}")
    
    # final_state = await app_graph.ainvoke(initial_state)
    
    # print("\n--- ✅ Grafo Finalizado ---")
    # print("Estado final del workflow:")
    # print(final_state)
    

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
               
    


 
    
    
