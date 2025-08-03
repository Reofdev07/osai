import tempfile
import httpx
import os



async def process_document_graph(file_path: str, job_id: str):
    """
    Esta función representa todo el workflow de LangGraph.
    Recibe la ruta al archivo y hace todo el trabajo.
    """
    print(f"⚙️ Grafo [Job {job_id}]: Iniciando procesamiento para el archivo {file_path}")
    
    # 1. Detectar tipo de archivo (PDF/Imagen)
    # 2. Extraer contenido (Texto/OCR)
    # 3. Contar tokens
    # 4. Resumir, clasificar, etc.
    
    # Simularemos un error para ver si la limpieza funciona
    # if job_id.startswith("a"): # Simula un error en algunos casos
    #     raise ValueError("¡Error de procesamiento simulado en el grafo!")

    print(f"✅ Grafo [Job {job_id}]: Procesamiento completado.")
    

async def stream_download_file(url: str, job_id: str):
    """
      Downloads a file from a URL and saves it to a temporary location.
      Returns the path to the downloaded file.
    """
    
    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, f"{job_id}.tmp")

    print(f"Iniciando Job [{job_id}]: Descargando de {url}")
    
    try:
      # --- PARTE 1: DESCARGA COMPLETA ---
        print(f"Iniciando Job [{job_id}]: Descargando desde {url}")
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
               
    print(f"✅ Job [{job_id}]: Descarga completada. El archivo está en {temp_file_path}")
    print(f"➡️ Job [{job_id}]: Ahora, iniciaríamos el grafo de LangGraph con la ruta del archivo...")
    