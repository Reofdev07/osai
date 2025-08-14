import httpx
import hmac
import hashlib
import json
from typing import Any, Dict, Optional

from app.core.config import settings



async def notify_steps_to_laravel(
    job_id: str,
    node_name: str,
    status: str = None,
    data: Optional[Dict[str, Any]] = None,
    step: str = None,
) -> bool:
    """
    Sends a notification to a Laravel queue.
    
    - job_id: ID del trabajo.
    - node_name: Nombre del nodo que generó el evento.
    - status: Estado del evento (inicial, procesado, finalizado).
    - data: Datos adicionales del evento.

    Retorna True si la notificación fue exitosa, False si hubo error.
    """
    
    webhook_url = settings.WEBHOOK_URL
    
    payload = {
        "job_id": job_id,
        "node": node_name,
        "status": status,
        "data": data or {}, # Datos adicionales del paso (ej. resumen, clasificación)
        "step": step
    }
    
    # Serializar el cuerpo de la solicitud para la firma
    request_body = json.dumps(payload).encode('utf-8')
    
    # Generar la firma HMAC-SHA256
    #signature = hmac.new(settings.WEBHOOK_SECRET.encode('utf-8'), request_body, hashlib.sha256).hexdigest()
    
    headers = {
        "Content-Type": "application/json",
        #"X-Webhook-Signature": f"sha256={signature}"
    }
    
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            print(f"Job [{job_id}]: Notificando a Laravel -> Nodo: {node_name}, Estado: {status}")
            response = await client.post(webhook_url, data=request_body, headers=headers)
            response.raise_for_status()  # Lanza error para respuestas 4xx/5xx
            return True
        except httpx.HTTPStatusError as e:
            print(f"Error de estado al notificar a Laravel para el job {job_id}: {e.response.status_code} - {e.response.text}")
            return False
        except httpx.RequestError as e:
            print(f"Error de red al notificar a Laravel para el job {job_id}: {e}")
            return False
