import uuid

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, HttpUrl

from ...utils.util import stream_download_file
from ...agents.basic_response_agent import basic_response_agent
from ...agents.chat_expert_agent import expert_chat_stream_generator

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
    # Necesitamos extraer el contexto del documento para el prompt de sistema.
    # El Job de Laravel ya nos lo está enviando.
    # Por ahora, asumiremos que el payload de 'messages' es lo principal.
    
    # En el futuro Job de Laravel, deberíamos añadir el 'document_subject', 'document_summary', etc. al payload.
    # Por ahora, lo simularemos.
    
    # Unimos la información
    full_payload = {**payload}
    return StreamingResponse(expert_chat_stream_generator(full_payload), media_type="text/plain")