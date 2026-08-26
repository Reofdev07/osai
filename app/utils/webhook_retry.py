"""
Reenvío de webhooks pendientes a Laravel.

Cuando OSAI no puede notificar a Laravel (caída/red), el payload se guarda en
disco (data/pending_webhooks/ y data/pending_portal_webhooks/). Este módulo
reintenta entregarlos periódicamente:

- Firma cada payload de nuevo con HMAC-SHA256 (mismo formato que notifications.py).
- Hace POST al WEBHOOK_URL / PORTAL_WEBHOOK_URL correspondiente.
- Si responde 2xx -> borra el archivo (entregado).
- Si falla -> conserva el archivo para el siguiente intento.

Se inicia como tarea asyncio en el startup de la app (app/main.py), de forma
análoga al worker de la cola offline (process_pending_jobs).

Importante: Laravel ya trata los webhooks de forma idempotente, así que reenviar
un 'finished' ya procesado no duplica telemetría ni trazabilidad.
"""
import asyncio
import glob
import hashlib
import hmac
import json
import logging
import os

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# (directorio, url de destino). Un directorio se omite si su URL no está configurada.
PENDING_DIRS = [
    ("data/pending_webhooks", os.getenv("WEBHOOK_URL", "")),
    ("data/pending_portal_webhooks", os.getenv("PORTAL_WEBHOOK_URL", "")),
]

RETRY_INTERVAL_SECONDS = int(os.getenv("WEBHOOK_RETRY_INTERVAL_SECONDS", "300"))
TIMEOUT_SECONDS = 15


def _headers(payload: dict):
    """Firma el cuerpo con HMAC-SHA256 y devuelve (body, headers)."""
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_SECRET:
        signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={signature}"
    return body, headers


async def retry_pending_webhooks_once() -> int:
    """Intenta reenviar una vez todos los webhooks pendientes.

    Retorna cuántos se entregaron y borraron correctamente.
    """
    delivered = 0

    for directory, url in PENDING_DIRS:
        if not url or not os.path.isdir(directory):
            continue

        for filepath in glob.glob(os.path.join(directory, "*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as e:  # noqa: BLE001
                logger.warning("Webhook retry: no se pudo leer %s: %s", filepath, e)
                continue

            body, headers = _headers(payload)
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                    resp = await client.post(url, content=body, headers=headers)
                if resp.status_code < 300:
                    os.remove(filepath)
                    delivered += 1
                    logger.info("Webhook retry: entregado %s (%s)", os.path.basename(filepath), resp.status_code)
                else:
                    logger.warning("Webhook retry: %s respondió %s, se conserva", os.path.basename(filepath), resp.status_code)
            except Exception as e:  # noqa: BLE001
                logger.warning("Webhook retry: %s error %s, se conserva", os.path.basename(filepath), e)

    return delivered


async def start_webhook_retry_worker(interval_seconds: int = None) -> None:
    """Loop infinito que reintenta webhooks pendientes cada N segundos.

    Nunca lanza: ante cualquier error espera el intervalo y continúa.
    """
    interval = interval_seconds or RETRY_INTERVAL_SECONDS
    logger.info("Webhook retry worker iniciado (cada %ss)", interval)
    while True:
        try:
            await retry_pending_webhooks_once()
        except Exception as e:  # noqa: BLE001
            logger.error("Webhook retry worker: error inesperado %s", e)
        await asyncio.sleep(interval)