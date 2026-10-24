import uuid
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from ...utils.portal_util import portal_stream_download_file

portal_router = APIRouter(prefix="/documents", tags=["Portal Document Analysis"])

class PortalAnalyzeRequest(BaseModel):
    file_url: HttpUrl
    document_id: int

@portal_router.post("/portal-analyze")
async def portal_analyze(request: PortalAnalyzeRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    background_tasks.add_task(portal_stream_download_file, str(request.file_url), job_id)
    return {"message": "Análisis portal iniciado.", "job_id": job_id}