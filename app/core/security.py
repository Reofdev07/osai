# app/core/security.py
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import API_TOKENS

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    if token not in API_TOKENS:
        raise HTTPException(status_code=403, detail="Token inválido o no autorizado")
    return API_TOKENS[token]
