"""
Reenvío de webhooks pendientes a Laravel (outbox en disco, ver webhook_outbox.py).

Cada ciclo, por directorio:
- Recupera archivos reclamados por un proceso que murió a mitad del envío.
- Reclama cada pendiente (rename atómico) antes de enviarlo: con varios workers no se duplica.
- 2xx -> borra; respuesta permanente (400/404/409/410/422) -> dead_webhooks; otro fallo -> vuelve
  a pendientes con un intento más, y al llegar a WEBHOOK_MAX_ATTEMPTS pasa a dead_webhooks.
La firma (v2, con timestamp) se calcula al reenviar, no al guardar.
Laravel trata los webhooks de forma idempotente: reenviar un 'finished' ya procesado no duplica.
"""
import asyncio
import glob
import logging
import os

from app.utils import webhook_outbox as outbox

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# (directorio, url de destino). Un directorio se omite si su URL no está configurada.
PENDING_DIRS = [
    (outbox.STATUS_DIR, os.getenv("WEBHOOK_URL", "")),
    (outbox.PORTAL_DIR, os.getenv("PORTAL_WEBHOOK_URL", "")),
]

RETRY_INTERVAL_SECONDS = int(os.getenv("WEBHOOK_RETRY_INTERVAL_SECONDS", "300"))


async def retry_pending_webhooks_once() -> int:
    """Intenta reenviar una vez todos los webhooks pendientes. Retorna cuántos se entregaron."""
    delivered = 0

    for directory, url in PENDING_DIRS:
        if not url or not os.path.isdir(directory):
            continue

        recovered = outbox.recover_stale_claims(directory)
        if recovered:
            logger.warning("Webhook retry: %s envíos interrumpidos devueltos a pendientes en %s", recovered, directory)

        for filepath in glob.glob(os.path.join(directory, "*.json")):
            claimed = outbox.claim(filepath)
            if not claimed:
                continue  # otro worker lo tomó
            try:
                payload, _, _ = outbox.read(claimed)
            except Exception as e:  # noqa: BLE001
                outbox.dead_letter(claimed, f"archivo ilegible: {e}")
                continue

            status = await outbox.send(url, payload, WEBHOOK_SECRET)
            name = os.path.basename(filepath)
            if status is not None and status < 300:
                os.remove(claimed)
                delivered += 1
                logger.info("Webhook retry: entregado %s (%s)", name, status)
            elif status in outbox.PERMANENT_STATUS:
                outbox.dead_letter(claimed, f"respuesta permanente {status}")
            else:
                if outbox.release(claimed, attempts_done=1):
                    logger.warning("Webhook retry: %s respondió %s, se reintentará", name, status)

    return delivered


async def start_webhook_retry_worker(interval_seconds: int = None) -> None:
    """Loop infinito que reintenta webhooks pendientes cada N segundos. Nunca lanza."""
    interval = interval_seconds or RETRY_INTERVAL_SECONDS
    logger.info("Webhook retry worker iniciado (cada %ss)", interval)
    while True:
        try:
            await retry_pending_webhooks_once()
        except Exception as e:  # noqa: BLE001
            logger.error("Webhook retry worker: error inesperado %s", e)
        await asyncio.sleep(interval)
