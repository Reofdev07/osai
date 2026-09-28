"""Outbox en disco de los webhooks OSAI -> Laravel.

Garantías (SGD-074/075/076/077/116):
- El webhook se escribe en disco ANTES de enviarlo y solo se borra con un 2xx: si OSAI cae a mitad
  de un envío, el payload sigue en disco y lo entrega el worker de reintento.
- Un archivo se "reclama" renombrándolo (atómico) antes de enviarlo: el envío inicial y el worker de
  reintento nunca mandan el mismo archivo a la vez, aunque haya varios workers.
- Nombres únicos (job + ns + aleatorio): dos fallos del mismo job en el mismo segundo no se pisan.
- Nada se borra por antigüedad: tras WEBHOOK_MAX_ATTEMPTS intentos o un error permanente del
  payload, el archivo pasa a data/dead_webhooks/ con un log de error (revisable y recuperable).

Formato del archivo: {"_outbox": {"attempts": N, "created_at": epoch}, "payload": {...}}.
Los archivos antiguos (payload crudo, sin "_outbox") se aceptan con attempts=0.
"""
import json
import logging
import os
import shutil
import time
import uuid

import httpx

from app.utils.webhook_signing import signed_headers

logger = logging.getLogger(__name__)

STATUS_DIR = "data/pending_webhooks"
PORTAL_DIR = "data/pending_portal_webhooks"
DEAD_DIR = "data/dead_webhooks"
CLAIM_SUFFIX = ".claimed"
MAX_ATTEMPTS = int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "288"))  # 24 h con reintentos cada 5 min
STALE_CLAIM_SECONDS = 600
RAW_TEXT_LIMIT = 50000
# Respuestas que no cambian al reintentar: el payload no es aceptable o el documento ya no existe.
PERMANENT_STATUS = {400, 404, 409, 410, 422}


def _compact(payload: dict) -> dict:
    """No guardar en disco el texto OCR completo (puede pesar MB); Laravel no lo necesita entero."""
    data = payload.get("data")
    if isinstance(data, dict):
        raw_text = data.get("raw_text")
        if isinstance(raw_text, str) and len(raw_text) > RAW_TEXT_LIMIT:
            payload = {**payload, "data": {**data, "raw_text": raw_text[:RAW_TEXT_LIMIT] + "... [TRUNCADO POR ESPACIO]"}}
    return payload


def _write(path: str, payload: dict, attempts: int, created_at: float) -> None:
    tmp = f"{path}.tmp-{uuid.uuid4().hex[:6]}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"_outbox": {"attempts": attempts, "created_at": created_at}, "payload": payload}, f, ensure_ascii=False)
    os.replace(tmp, path)


def read(path: str) -> tuple[dict, int, float]:
    with open(path, "r", encoding="utf-8") as f:
        content = json.load(f)
    if isinstance(content, dict) and "_outbox" in content and "payload" in content:
        meta = content["_outbox"] or {}
        return content["payload"], int(meta.get("attempts", 0)), float(meta.get("created_at", time.time()))
    return content, 0, os.path.getmtime(path)


def enqueue_claimed(directory: str, payload: dict) -> str:
    """Escribe el webhook ya reclamado (el worker de reintento lo ignora mientras se envía)."""
    os.makedirs(directory, exist_ok=True)
    name = f"{payload.get('job_id', 'unknown')}_{time.time_ns()}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(directory, name + CLAIM_SUFFIX)
    _write(path, _compact(payload), attempts=0, created_at=time.time())
    return path


def claim(path: str) -> str | None:
    claimed = path + CLAIM_SUFFIX
    try:
        os.rename(path, claimed)
        return claimed
    except (FileNotFoundError, PermissionError):
        return None


def release(claimed_path: str, attempts_done: int) -> bool:
    """Devuelve el archivo a pendientes sumando intentos. Retorna False si agotó el máximo y se
    mandó a dead_webhooks."""
    payload, attempts, created_at = read(claimed_path)
    attempts += attempts_done
    if attempts >= MAX_ATTEMPTS:
        dead_letter(claimed_path, f"agotó {attempts} intentos")
        return False
    _write(claimed_path, payload, attempts, created_at)
    os.replace(claimed_path, claimed_path[: -len(CLAIM_SUFFIX)])
    return True


def dead_letter(path: str, reason: str) -> None:
    os.makedirs(DEAD_DIR, exist_ok=True)
    name = os.path.basename(path).removesuffix(CLAIM_SUFFIX)
    target = os.path.join(DEAD_DIR, name)
    shutil.move(path, target)
    logger.error("Webhook enviado a dead_webhooks (%s): %s", reason, target)
    print(f"❌ Webhook sin entregar movido a {target}: {reason}")


def recover_stale_claims(directory: str) -> int:
    """Archivos reclamados por un proceso que murió a mitad del envío vuelven a pendientes."""
    recovered = 0
    if not os.path.isdir(directory):
        return 0
    for name in os.listdir(directory):
        if not name.endswith(CLAIM_SUFFIX):
            continue
        path = os.path.join(directory, name)
        try:
            if time.time() - os.path.getmtime(path) > STALE_CLAIM_SECONDS:
                os.replace(path, path[: -len(CLAIM_SUFFIX)])
                recovered += 1
        except FileNotFoundError:
            continue
    return recovered


async def send(url: str, payload: dict, secret: str, timeout: float = 15) -> int | None:
    """POST firmado (v2, timestamp del momento del envío). Devuelve el status HTTP o None si no hubo respuesta."""
    body = json.dumps(payload).encode("utf-8")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, content=body, headers=signed_headers(body, secret))
        return resp.status_code
    except httpx.HTTPError as e:
        logger.warning("Webhook a %s sin respuesta: %s", url, e)
        return None


async def deliver(directory: str, url: str, payload: dict, secret: str, tries: int = 3) -> bool:
    """Outbox: guarda, intenta `tries` veces y, si no se entrega, deja el archivo para el reintento."""
    import asyncio

    path = enqueue_claimed(directory, payload)
    for attempt in range(tries):
        status = await send(url, payload, secret)
        if status is not None and status < 300:
            os.remove(path)
            return True
        if status in PERMANENT_STATUS:
            dead_letter(path, f"respuesta permanente {status}")
            return False
        if attempt < tries - 1:
            await asyncio.sleep(2**attempt)
    release(path, attempts_done=tries)
    return False
