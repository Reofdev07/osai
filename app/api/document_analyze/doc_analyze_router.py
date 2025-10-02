
import uuid
import asyncio

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, HttpUrl

from ...utils.util import stream_download_file
from ...agents.basic_response_agent import basic_response_agent
from ...core.llm import create_llm

# instance of LLM
llm = create_llm()

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

    


async def stream_generator(full_payload: dict):
    """
    Este es un generador. LangChain nos da un iterador, y nosotros
    lo recorremos y hacemos 'yield' de cada trozo de contenido.
    FastAPI se encargará de enviar cada 'yield' al cliente.
    """


    # 1. Extraemos el contexto real que nos envía el frontend
    context = full_payload.get('context', {})
    
    # Extraemos las secciones del contexto con seguridad
    info = context.get('general_info', {})
    analysis = context.get('ai_analysis', {})
    parties = context.get('parties', {})
    history = context.get('history', [])
    task = context.get('current_task', {})

    # Formateamos el historial para que sea legible
    history_str = "\n".join([f"- {h['date']}: {h['description']} (Por: {h['user']})" for h in history]) if history else "No hay historial de eventos."

    # Construimos un System Prompt de nivel experto
    system_prompt = f"""
    Eres un asistente experto para la gestión de expedientes. Estás trabajando en el caso #{info.get('radicado_number', 'N/A')}.
    El usuario actual es {info.get('responsible_user', 'un funcionario')} y su tarea pendiente es: "{task.get('name', 'Revisar el caso')}".
    Tu objetivo es ayudarlo a completar esta tarea.

    === CONTEXTO COMPLETO DEL EXPEDIENTE ===
    
    **1. Información General:**
    - Asunto: {info.get('subject', 'N/A')}
    - Remitente (Ciudadano/Entidad): {info.get('sender', 'N/A')}
    - Fecha Límite de Respuesta: {info.get('response_deadline_at', 'N/A')}
    - Estado Actual del Caso: {info.get('current_status', 'N/A')}
    - Dependencia Responsable: {info.get('dependency', 'N/A')}

    **2. Análisis Automático del Documento Principal:**
    - Resumen: {analysis.get('summary', 'N/A')}
    - Intención Detectada: {analysis.get('intent', {}).get('intencion', 'N/A')}
    - Partes Involucradas:
        - Solicitante: {parties.get('claimant', 'N/A')}
        - Demandado: {parties.get('defendant', 'N/A')}
    - Hechos Relevantes: {analysis.get('entities', {}).get('hechos_relevantes', ['N/A'])}
    
    **3. Historial Reciente del Caso (últimos eventos):**
    {history_str}

    === FIN DEL CONTEXTO ===

    Basándote ESTRICTAMENTE en el contexto anterior y en la conversación, responde al usuario.
    Anticipa sus necesidades relacionadas con su tarea pendiente. Sé preciso, profesional y no inventes información.
    Utiliza formato Markdown para mejorar la legibilidad de tus respuestas.
    """

    # 3. Preparamos el historial de mensajes para LangChain
    #    LangChain funciona mejor con objetos de mensaje específicos.
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    messages_for_llm = [SystemMessage(content=system_prompt)]


    # Añadimos el historial de chat, convirtiéndolo al formato de LangChain
    for msg in full_payload.get('messages', []):
        if msg['role'] == 'user':
            messages_for_llm.append(HumanMessage(content=msg['content']))
        elif msg['role'] == 'assistant':
            messages_for_llm.append(AIMessage(content=msg['content']))
            
    # 4. Llamamos al LLM con el contexto completo (System Prompt + Historial)
    response_stream = llm.astream(messages_for_llm)

    async for chunk in response_stream:
        if chunk.content:
            yield chunk.content



    # user_message = full_payload['messages'][-1]['content']
    
    # # 1. Reemplazamos .invoke() por .stream()
    # # Esto devuelve un iterador de AIMessageChunk, no una respuesta final.
    # response_stream = llm.astream(user_message)
    
    # # 2. Iteramos sobre los chunks que LangChain nos va entregando
    # async for chunk in response_stream:
    #     # 'chunk' NO es un string. Es un objeto, usualmente AIMessageChunk.
    #     # El contenido de texto está en el atributo .content.
    #     print(f"Yielding chunk: {chunk.content}") # Para depurar en la consola de FastAPI
    #     yield chunk.content


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
    return StreamingResponse(stream_generator(full_payload), media_type="text/plain")