
import uuid

from fastapi import APIRouter, BackgroundTasks

from pydantic import BaseModel, HttpUrl

from ...utils.webhook_notifier import WebhookNotifier
from ...utils.webhooks import call_webhook
from ...utils.util import stream_download_file

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