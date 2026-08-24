import tempfile
import httpx
import os
import asyncio
from urllib.parse import urlparse

from ..graphs.portal_pqrsd_graph import portal_graph
from .portal_notifications import notify_portal_steps
from .url_security import is_safe_url


async def portal_process_document_graph(file_path: str, job_id: str):
    print(f"Portal Grafo [Job {job_id}]: Iniciando procesamiento...")

    initial_state = {"job_id": job_id, "file_path": file_path}
    accumulated_state = initial_state.copy()
    config = {"configurable": {"thread_id": job_id}}

    async for step in portal_graph.astream(initial_state, config=config):
        for node_name, step_output in step.items():
            print(f"Job [{job_id}]: Progreso -> Nodo '{node_name}' completado.")
            step_output = dict(step_output) if step_output else {}
            accumulated_state.update(step_output)

    final_status = "finished"
    final_message = "Análisis portal completado."
    if accumulated_state.get("error") or (accumulated_state.get("errors") and len(accumulated_state["errors"]) > 0):
        final_status = "finished_with_errors"
        final_message = "Análisis portal finalizado con datos parciales."

    await notify_portal_steps(
        job_id=job_id,
        node_name="graph_process",
        status=final_status,
        data=accumulated_state,
        step=final_message
    )

    print(f"Job [{job_id}]: Proceso del grafo portal completado.")
    return accumulated_state


MAX_CONCURRENT_DOCS = 5
doc_processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOCS)


async def portal_stream_download_file(url: str, job_id: str):
    print(f"Job [{job_id}]: En cola portal. Esperando turno de procesamiento...")
    async with doc_processing_semaphore:
        print(f"Job [{job_id}]: Turno asignado. Iniciando descarga y proceso portal...")
        temp_file_path = None
        try:
            parsed_url = urlparse(str(url))
            _, file_extension = os.path.splitext(os.path.basename(parsed_url.path))
            if not file_extension:
                print(f"Job [{job_id}]: La ruta de la URL no contiene una extensión de archivo válida.")
                return
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension, prefix="osai_portal_") as temp_file:
                temp_file_path = temp_file.name
            # --- SEGURIDAD SSRF: validar la URL antes de descargarla ---
            if not is_safe_url(str(url)):
                print(f"Job [{job_id}]: URL no permitida (posible SSRF). Abortando.")
                return

            async with httpx.AsyncClient() as client:
                async with client.stream("GET", str(url), follow_redirects=False, timeout=60.0) as response:
                    response.raise_for_status()
                    with open(temp_file_path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
            await portal_process_document_graph(file_path=temp_file_path, job_id=job_id)
        except Exception as e:
            print(f"Error en Job [{job_id}]: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)