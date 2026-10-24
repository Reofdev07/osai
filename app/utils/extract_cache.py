"""Caché en disco del texto extraído por visión, por sha256 del archivo.

Un reintento de Laravel del mismo archivo no vuelve a pagar la visión. Privacidad: carpeta 0700 y archivos 0600,
sin URLs ni nombres de archivo (solo el hash), TTL EXTRACT_CACHE_DAYS (0 = apagada) y tope EXTRACT_CACHE_MAX_MB.
Todas las funciones son síncronas: llamarlas con run_cpu desde código async.
"""
import hashlib
import json
import os
import re
import time

from app.core.config import settings

_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION = "v1"


def enabled() -> bool:
    return settings.EXTRACT_CACHE_DAYS > 0


def file_key(path: str) -> str:
    """sha256 del archivo (por bloques) con la versión del formato de caché."""
    h = hashlib.sha256(VERSION.encode())
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _path(key: str) -> str | None:
    return os.path.join(settings.EXTRACT_CACHE_DIR, key + ".json") if _KEY_RE.match(key or "") else None


def load(key: str) -> dict | None:
    """Entrada vigente o None. Una entrada vencida o ilegible se borra."""
    path = _path(key)
    if not enabled() or not path or not os.path.exists(path):
        return None
    try:
        if time.time() - os.path.getmtime(path) > settings.EXTRACT_CACHE_DAYS * 86400:
            os.remove(path)
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        return None


def save(key: str, data: dict) -> None:
    """Guarda de forma atómica con permisos restringidos y luego aplica TTL y tope de tamaño. Nunca lanza."""
    path = _path(key)
    if not enabled() or not path:
        return
    try:
        folder = settings.EXTRACT_CACHE_DIR
        os.makedirs(folder, mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
        tmp = f"{path}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        _enforce_limits()
    except Exception as e:
        print(f"⚠️ Caché de extracción: no se pudo guardar ({type(e).__name__}).")


def _enforce_limits() -> None:
    folder = settings.EXTRACT_CACHE_DIR
    now = time.time()
    entries = []
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        if not name.endswith(".json") or not os.path.isfile(full):
            continue
        st = os.stat(full)
        if now - st.st_mtime > settings.EXTRACT_CACHE_DAYS * 86400:
            os.remove(full)
            continue
        entries.append((st.st_mtime, st.st_size, full))
    limit = settings.EXTRACT_CACHE_MAX_MB * 1024 * 1024
    total = sum(e[1] for e in entries)
    for _, size, full in sorted(entries):  # primero las más antiguas
        if total <= limit:
            break
        os.remove(full)
        total -= size
