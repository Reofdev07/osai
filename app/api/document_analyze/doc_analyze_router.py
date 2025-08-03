
import aiohttp
import base64
import requests
import uuid

from fastapi import APIRouter, File, UploadFile, BackgroundTasks, HTTPException

from typing import List
from pydantic import BaseModel, HttpUrl

from ...utils.webhook_notifier import WebhookNotifier
from ...utils.webhooks import call_webhook
from ...utils.utils import stream_download_file

# Crear el router
doc_analyze_router = APIRouter(
    prefix="/documents",
    tags=["Document Analysis"],
)

class FileUrlRequest(BaseModel):
    file_url: HttpUrl
    

@doc_analyze_router.post("/analyze")
async def analyze_url(
    request: FileUrlRequest , 
    background_tasks: BackgroundTasks
    ):
        job_id = str(uuid.uuid4())
        
        background_tasks.add_task(stream_download_file, request.file_url, job_id)
        
        return {
        "message": "El procesamiento del documento ha comenzado.", 
        "job_id": job_id
        }

    # try:
        
        
        
        
    #     print(f"Descargando archivo desde {request.file_url}")
    #     response = requests.get(request.file_url)
    #     response.raise_for_status()
    # except Exception as e:
    #     raise HTTPException(status_code=400, detail=f"Error downloading file: {e}")

    # # Aquí procesas el contenido del archivo
    # content = response.content
    # # Por ejemplo, podrías detectar si es PDF, imagen, etc. y mandarlo a procesar
    # result = process_file(content)
    # #Llamas al webhook de Laravel asincrónicamente
    # webhook_url = "http://localhost:8000/api/webhooks/fastapi/status-update"
    # payload = {
    #     "message": "Document analysis is not yet implemented.",
    # }
    # #print(f"📡 Llamando al webhook: {webhook_url}")
    # await call_webhook(webhook_url, payload)

    # return result  # puede ser dict, JSON, etc.





def process_file(content: bytes):
    # Procesamiento simulado
    return {"status": "ok", "message": "Archivo procesado correctamente"}

    

# @doc_analyze_router.post("/analyze")
# async def analyze_document(request: DocumentAnalysis):
#     """
#     """
#     async with aiohttp.ClientSession() as session:
#             for url in request.urls:
#                 #print(f"📥 Descargando desde: {url}")
#                 try:
#                     async with session.get(url) as resp:
#                         if resp.status == 200:
#                             print('ok')
                            
#                             # content = await resp.read()
#                             # encoded_content = base64.b64encode(content).decode("utf-8")
            
#                         else:
#                            print(f"❌ Error al descargar {url}: Status {resp.status}")
#                 except Exception as e:
#                     print(f"⚠️ Error al intentar descargar {url}: {e}")

#             # Llamas al webhook de Laravel asincrónicamente
#             webhook_url = "http://localhost:8000/api/webhooks/fastapi/status-update"
#             payload = {
#                 "message": "Document analysis is not yet implemented.",
#             }
#             #print(f"📡 Llamando al webhook: {webhook_url}")
#             await call_webhook(webhook_url, payload)

#     return {
#         "message": "Document analysis is not yet implemented.",
#     }