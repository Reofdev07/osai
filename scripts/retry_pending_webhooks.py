#!/usr/bin/env python3
"""
Reenvío de webhooks pendientes a Laravel.

Lee los JSON guardados en data/pending_webhooks/ y data/pending_portal_webhooks/,
los firma de nuevo (HMAC-SHA256) y los reenvía. Los que se entreguen (2xx) se
borran; los que fallen se conservan para un próximo intento.

Uso:
  python3 scripts/retry_pending_webhooks.py            # reenviar y borrar los OK
  python3 scripts/retry_pending_webhooks.py --dry-run  # solo mostrar
"""
import os, json, glob, hmac, hashlib, sys, time

import httpx

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORTAL_WEBHOOK_URL = os.getenv("PORTAL_WEBHOOK_URL", "")

DIRS = [
    ("data/pending_webhooks", WEBHOOK_URL),
    ("data/pending_portal_webhooks", PORTAL_WEBHOOK_URL),
]


def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def _headers(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if WEBHOOK_SECRET:
        sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={sig}"
    return body, headers


def retry(dry_run: bool = False):
    total_sent = total_ok = total_fail = 0

    for dir_path, url in DIRS:
        if not os.path.exists(dir_path) or not url:
            continue

        for fp in glob.glob(os.path.join(dir_path, "*.json")):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as e:
                log(f"⚠️ No se pudo leer {fp}: {e}")
                continue

            if dry_run:
                log(f"[dry-run] Reenviaría {os.path.basename(fp)}")
                total_sent += 1
                continue

            body, headers = _headers(payload)
            try:
                resp = httpx.post(url, content=body, headers=headers, timeout=15)
                if resp.status_code < 300:
                    os.remove(fp)
                    log(f"✅ {os.path.basename(fp)} entregado ({resp.status_code}). Borrado.")
                    total_ok += 1
                else:
                    log(f"⚠️ {os.path.basename(fp)} respondió {resp.status_code}. Se conserva.")
                    total_fail += 1
            except Exception as e:
                log(f"❌ {os.path.basename(fp)} error: {e}. Se conserva.")
                total_fail += 1
            total_sent += 1

    if dry_run:
        log(f"[dry-run] Total a reenviar: {total_sent}")
    else:
        log(f"Total: {total_sent} (OK: {total_ok}, fallaron: {total_fail})")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    retry(dry_run)