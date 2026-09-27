import uuid
import logging

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, HttpUrl

from ...utils.util import stream_download_file
from ...agents.basic_response_agent import basic_response_agent
from ...agents.chat_expert_agent import expert_chat_stream_generator
from ...agents.typology_suggestion_agent import suggest_typology_agent
from ...core.database import get_db_connection
from ...core.offline_queue import mark_job_completed, mark_job_failed

logger = logging.getLogger(__name__)

# Crear el router
doc_analyze_router = APIRouter(
    prefix="/documents",
    tags=["Document Analysis"],
)

class FileUrlRequest(BaseModel):
    file_url: HttpUrl
    document_id: int
    

@doc_analyze_router.post("/analyze")
async def analyze_url(
    request: FileUrlRequest,
    background_tasks: BackgroundTasks,
):
    job_id = str(uuid.uuid4())

    try:
        from datetime import datetime
        with get_db_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pending_ai_jobs
                   (id, document_id, file_url, status, created_at, retry_count)
                   VALUES (?, ?, ?, 'processing', ?, 0)""",
                (job_id, request.document_id, str(request.file_url), datetime.now().isoformat()),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"No se pudo persistir job {job_id} en la cola: {e}")

    async def _run_and_track(file_url, jid):
        try:
            await stream_download_file(file_url, jid)
            await mark_job_completed(jid)
        except Exception as exc:
            await mark_job_failed(jid, str(exc)[:500])
            raise

    background_tasks.add_task(_run_and_track, request.file_url, job_id)

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


@doc_analyze_router.post("/suggest-typology")
async def suggest_typology(payload: dict):
    """
    Endpoint que sugiere la tipología documental basada en el contenido del documento.
    Recibe el resumen y contenido del documento y retorna la tipología sugerida.
    """
    return StreamingResponse(suggest_typology_agent(payload), media_type="text/plain")