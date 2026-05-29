import httpx
import json
import asyncio
import os
import hmac
import hashlib
from typing import Any, Dict, Optional

from app.core.config import settings

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


async def notify_portal_steps(
    job_id: str,
    node_name: str,
    status: str = None,
    data: Optional[Dict[str, Any]] = None,
    step: str = None,
) -> bool:
    callback_url = settings.PORTAL_WEBHOOK_URL
    if not callback_url:
        print(f"Job [{job_id}]: PORTAL_WEBHOOK_URL no está configurado.")
        return False

    payload = {
        "job_id": job_id,
        "node": node_name,
        "status": status,
        "data": data or {},
        "step": step
    }
    request_body = json.dumps(payload).encode('utf-8')
    headers = {"Content-Type": "application/json"}

    if WEBHOOK_SECRET:
        signature = hmac.new(
            WEBHOOK_SECRET.encode(),
            request_body,
            hashlib.sha256
        ).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"

    MAX_RETRIES = 3
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(MAX_RETRIES):
            try:
                print(f"Job [{job_id}]: Notificando resultado final a Laravel portal (Intento {attempt + 1}/{MAX_RETRIES})")
                response = await client.post(callback_url, content=request_body, headers=headers)
                response.raise_for_status()
                return True
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                print(f"Job [{job_id}]: Error al notificar resultado final: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    print(f"Job [{job_id}]: Fallaron todos los intentos. La notificación final no pudo ser entregada.")
                    return False
    return False