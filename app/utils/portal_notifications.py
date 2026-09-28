import os
from typing import Any, Dict, Optional

from app.core.config import settings
from app.utils.notifications import build_payload
from app.utils.webhook_outbox import PORTAL_DIR, deliver

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")


async def notify_portal_steps(
    job_id: str,
    node_name: str,
    status: str = None,
    data: Optional[Dict[str, Any]] = None,
    step: str = None,
) -> bool:
    """Notifica al webhook del portal PQRSD. Mismo outbox que el de radicación (SGD-076): si no se
    entrega queda en data/pending_portal_webhooks en vez de perderse tras 3 intentos."""
    callback_url = settings.PORTAL_WEBHOOK_URL
    if not callback_url:
        print(f"Job [{job_id}]: PORTAL_WEBHOOK_URL no está configurado.")
        return False

    payload = build_payload(job_id, node_name, status, data, step)
    delivered = await deliver(PORTAL_DIR, callback_url, payload, WEBHOOK_SECRET)
    if not delivered:
        print(f"Job [{job_id}]: webhook del portal no entregado, queda en el outbox para reintento.")
    return delivered
