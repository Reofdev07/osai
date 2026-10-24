import uuid
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, HttpUrl

from ...utils.util import stream_download_file
from ...agents.basic_response_agent import basic_response_agent
from ...agents.chat_expert_agent import expert_chat_stream_generator
from ...agents.reference_text import REFERENCE_MAX_MB, ReferenceRejected, extract_reference_text
from ...core.offline_queue import mark_job_completed, mark_job_failed, persist_pending_job
from ...utils.filing_catalog import FilingCatalog

logger = logging.getLogger(__name__)

# Crear el router
doc_analyze_router = APIRouter(
    prefix="/documents",
    tags=["Document Analysis"],
)

class FileUrlRequest(BaseModel):
    file_url: HttpUrl
    document_id: int
    # Catálogo real de la entidad (Laravel con contrato 2). Nulo en lotes antiguos: la IA no sugiere ids.
    catalog: Optional[FilingCatalog] = None


@doc_analyze_router.post("/analyze")
async def analyze_url(
    request: FileUrlRequest,
    background_tasks: BackgroundTasks,
):
    job_id = str(uuid.uuid4())
    catalog = request.catalog.model_dump() if request.catalog else None

    try:
        persist_pending_job(job_id, request.document_id, str(request.file_url), catalog)
    except Exception as e:
        logger.error(f"No se pudo persistir job {job_id} en la cola: {e}")

    async def _run_and_track(file_url, jid, job_catalog):
        try:
            await stream_download_file(file_url, jid, job_catalog)
            await mark_job_completed(jid)
        except Exception as exc:
            await mark_job_failed(jid, str(exc)[:500])
            raise

    background_tasks.add_task(_run_and_track, request.file_url, job_id, catalog)

    return {
        "message": "El procesamiento del documento ha comenzado.",
        "job_id": job_id,
    }



@doc_analyze_router.post("/generate-summary-stream")
async def generate_summary_stream(payload: dict):
    """
    this function is a basic response agent that uses a LLM to generate a response to a task description.
    """
    # Pasamos el objeto 'payload' completo, que contiene todo el contexto,
    # directamente a nuestro agente.
    return StreamingResponse(basic_response_agent(payload))

    

@doc_analyze_router.post("/assistant/chat-stream")
async def chat_stream(payload: dict):
    """
    Endpoint que recibe el payload completo del chat de Laravel y activa el agente conversacional.
    """
    full_payload = {**payload}
    return StreamingResponse(expert_chat_stream_generator(full_payload), media_type="text/plain")


@doc_analyze_router.post("/assistant/reference-text")
async def reference_text(file: UploadFile = File(...)):
    """
    Texto de un documento que el funcionario sube al chat solo para consultarlo. El archivo no se guarda.
    422 con un mensaje para el funcionario si no sirve; 502 si la lectura falló.
    """
    data = await file.read(REFERENCE_MAX_MB * 1024 * 1024 + 1)
    try:
        return await extract_reference_text(data, file.filename or "")
    except ReferenceRejected as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Solo el tipo de error: el mensaje podría traer contenido del documento.
        logger.error(f"Documento de consulta del chat: no se pudo leer ({type(e).__name__}).")
        raise HTTPException(status_code=502, detail="No se pudo leer el documento. Intente de nuevo.")
