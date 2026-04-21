import httpx
import hmac
import hashlib
import json
import asyncio
import os
import time
from typing import Any, Dict, Optional

from app.core.config import settings

def save_pending_webhook(payload: dict):
    """Guarda en disco un webhook fallido para su posterior reenvío, optimizando el espacio."""
    try:
        os.makedirs("data/pending_webhooks", exist_ok=True)
        
        # --- Optimización: No guardar datos masivos de texto crudo en el respaldo ---
        # Si el payload es muy grande, es por el 'raw_text' de los documentos.
        if "data" in payload and isinstance(payload["data"], dict):
            raw_text = payload["data"].get("raw_text", "")
            if raw_text and len(raw_text) > 50000: # Si tiene más de 50KB de texto
                payload["data"]["raw_text"] = raw_text[:50000] + "... [TRUNCADO POR ESPACIO]"
                print(f"⚠️ Payload de respaldo truncado para ahorrar espacio ({len(raw_text)} chars -> 50k)")

        filename = f"data/pending_webhooks/{payload.get('job_id', 'unknown')}_{int(time.time())}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"💾 Webhook guardado en disco para reenvío futuro: {filename}")
    except Exception as e:
        print(f"❌ Error crítico al guardar webhook pendiente: {e}")

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

    Retorna True si la notificación fue exitosa, False si hubo error (pero se guardó localmente).
    """
    
    webhook_url = settings.WEBHOOK_URL
    print(f"webhook_url: {webhook_url}")
    
    payload = {
        "job_id": job_id,
        "node": node_name,
        "status": status,
        "data": data or {}, # Datos adicionales del paso (ej. resumen, clasificación)
        "step": step
    }
    
    # Serializar el cuerpo de la solicitud para la firma
    request_body = json.dumps(payload).encode('utf-8')
    
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Secret": settings.WEBHOOK_SECRET
    }
    
    MAX_RETRIES = 3
    async with httpx.AsyncClient(timeout=15) as client:
        for attempt in range(MAX_RETRIES):
            try:
                print(f"Job [{job_id}]: Notificando a Laravel (Intento {attempt + 1}/{MAX_RETRIES}) -> Nodo: {node_name}, Estado: {status}")
                response = await client.post(webhook_url, content=request_body, headers=headers)
                response.raise_for_status()  # Lanza error para respuestas 4xx/5xx
                return True
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                print(f"⚠️ Error al notificar a Laravel para el job {job_id}: {e}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = 2 ** attempt  # 1s, 2s
                    print(f"Reintentando en {wait_time} segundos...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ Fallaron los {MAX_RETRIES} intentos de webhook al job {job_id}.")
                    
                    # --- FILTRO: No guardar basura de Excel en disco ---
                    if node_name == "extract_office":
                        print(f"🚫 Nodo '{node_name}' falló pero NO se guardará respaldo (basura Excel detectada).")
                    else:
                        save_pending_webhook(payload)
                        
                    return False
