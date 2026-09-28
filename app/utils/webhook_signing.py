"""Firma HMAC de los webhooks OSAI -> Laravel.

v2 (SGD-146): se firma "{timestamp}.{body}" y se envía X-Webhook-Timestamp. Laravel rechaza firmas
fuera de su ventana (300 s), así un webhook capturado no se puede reenviar. El timestamp se genera
al ENVIAR (no al guardar un pendiente), por eso hay que llamar a esta función en cada intento.
"""
import hashlib
import hmac
import time


def signed_headers(body: bytes, secret: str | None) -> dict:
    headers = {"Content-Type": "application/json"}
    if secret:
        timestamp = str(int(time.time()))
        signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        headers["X-Webhook-Timestamp"] = timestamp
        headers["X-Webhook-Signature"] = f"sha256={signature}"
    return headers
