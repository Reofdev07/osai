# app/core/security.py
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    if token not in settings.API_TOKENS:
        raise HTTPException(status_code=403, detail="Token inválido o no autorizado")
    return token
