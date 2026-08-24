# app/core/security.py
import hmac
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import settings

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    allowed = settings.API_TOKENS
    # Comparación constante en tiempo (evita timing attack) y fail-closed
    if not allowed or not any(hmac.compare_digest(token, t) for t in allowed):
        raise HTTPException(status_code=403, detail="Token inválido o no autorizado")
    return token
