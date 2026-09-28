import itertools
import os
import time
from collections import defaultdict
from typing import Any, Dict, Optional

from app.core.config import settings
from app.utils.webhook_outbox import STATUS_DIR, deliver

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Versión del contrato OSAI -> Laravel (SGD-112): subirla si cambia la forma del payload.
CONTRACT_VERSION = 1

# SGD-080: secuencia por job para que Laravel descarte pasos que lleguen fuera de orden.
_sequences: dict[str, itertools.count] = defaultdict(lambda: itertools.count(1))


def build_payload(job_id: str, node_name: str, status: Optional[str], data: Optional[Dict[str, Any]], step) -> dict:
    return {
        "job_id": job_id,
        "node": node_name,
        "status": status,
        "data": data or {},  # Datos adicionales del paso (ej. resumen, clasificación)
        "step": step,
        "sequence": next(_sequences[job_id]),
        "emitted_at": time.time(),
        "contract_version": CONTRACT_VERSION,
    }


async def notify_steps_to_laravel(
    job_id: str,
    node_name: str,
    status: str = None,
    data: Optional[Dict[str, Any]] = None,
    step: str = None,
) -> bool:
    """Notifica un paso del análisis a Laravel.

    El payload se guarda en el outbox antes de enviarlo: si no se entrega en 3 intentos queda en
    data/pending_webhooks para el worker de reintento (nunca se pierde en silencio).
    Retorna True si Laravel lo confirmó.
    """
    payload = build_payload(job_id, node_name, status, data, step)
    if status in ("finished", "finished_with_errors", "failed_terminal"):
        _sequences.pop(job_id, None)

    print(f"Job [{job_id}]: Notificando a Laravel -> Nodo: {node_name}, Estado: {status}")
    delivered = await deliver(STATUS_DIR, settings.WEBHOOK_URL, payload, WEBHOOK_SECRET)
    if not delivered:
        print(f"⚠️ Job [{job_id}]: webhook no entregado, queda en el outbox para reintento.")
    return delivered
