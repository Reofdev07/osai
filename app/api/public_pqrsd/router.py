from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from app.agents.pqrsd_validator_agent import pqrsd_validator_agent

pqrsd_router = APIRouter(
    prefix="/public-pqrsd",
    tags=["Public PQRSD"]
)

class PqrsdInputPayload(BaseModel):
    subject: str
    description: str
    location: Optional[str] = ""

class PqrsdImprovePayload(BaseModel):
    tipo_solicitud: str
    subject: str
    hechos: str
    peticiones: str

@pqrsd_router.post("/validate")
async def validate_pqrsd(payload: PqrsdInputPayload):
    """
    Toma los datos del ciudadano, los analiza contra la Ley 1755
    y devuelve el JSON estructurado para el proxy de Laravel.
    """
    dict_payload = payload.model_dump()
    result = await pqrsd_validator_agent(dict_payload)
    return result

@pqrsd_router.post("/improve")
async def improve_pqrsd_text(payload: PqrsdImprovePayload):
    """
    Recibe un texto crudo y devuelve una versión mejorada (gramática, ortografía y tono formal).
    """
    from app.agents.pqrsd_improver_agent import pqrsd_improver_agent
    result = await pqrsd_improver_agent(payload.tipo_solicitud, payload.subject, payload.hechos, payload.peticiones)
    return result

