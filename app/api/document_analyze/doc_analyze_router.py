
import uuid
import asyncio

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, HttpUrl

from ...utils.util import stream_download_file
from ...agents.basic_response_agent import basic_response_agent

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
    request: FileUrlRequest , 
    background_tasks: BackgroundTasks
    ):
        job_id = str(uuid.uuid4())
        
        background_tasks.add_task(stream_download_file, request.file_url, job_id)
        
        return {
        "message": "El procesamiento del documento ha comenzado.", 
        "job_id": job_id,
        
        }


async def fake_llm_responder(context: str):
    """
    Simulador de un LLM generando una respuesta token por token.
    En el futuro, aquí iría la llamada real a OpenAI, Anthropic, etc.
    """
    prompt = f"Basado en el contexto '{context}', redacta una breve justificación para el historial del expediente."
    
    # Simulación de respuesta
    response_text = f"Se ha completado la acción correspondiente a: '{context}'. El proceso avanza a la siguiente etapa."
    
    for word in response_text.split():
        yield word + " "
        await asyncio.sleep(0.1) # Simula el tiempo de generación de cada token




@doc_analyze_router.post("/generate-summary-stream")
async def generate_summary_stream(payload: dict):
    # En una implementación real, 'payload' contendría todo el contexto del caso.
    task_description = payload.get("task_description", "Tarea no especificada")
    return StreamingResponse(basic_response_agent(task_description))