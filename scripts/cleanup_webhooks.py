#!/usr/bin/env python3
"""
Cleanup de webhooks fallidos para CRON diario.
Borra .json en data/pending_webhooks/ y data/pending_portal_webhooks/
con >7 días, >500 archivos, o >100MB por directorio.

Uso:
  python3 scripts/cleanup_webhooks.py               # normal
  python3 scripts/cleanup_webhooks.py --dry-run      # solo mostrar, no borrar
"""
import os, time, glob, sys

PENDING_DIRS = ["data/pending_webhooks", "data/pending_portal_webhooks"]
MAX_AGE_DAYS = 7
MAX_FILES = 500
MAX_SIZE_BYTES = 100 * 1024 * 1024


def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def cleanup(dry_run: bool = False):
    now = time.time()
    total_deleted = total_freed = 0

    for dir_path in PENDING_DIRS:
        if not os.path.exists(dir_path):
            continue

        files = []
        for fp in glob.glob(os.path.join(dir_path, "*.json")):
            try:
                st = os.stat(fp)
                files.append((st.st_mtime, st.st_size, fp))
            except OSError:
                continue

        if not files:
            continue

        files.sort(key=lambda x: x[0])
        before = len(files)
        dir_size = sum(s for _, s, _ in files)
        deleted = freed = 0
        kept = []

        # 1. Borrar por antigüedad
        for mtime, size, fp in files:
            if (now - mtime) / 86400 > MAX_AGE_DAYS:
                if dry_run:
                    log(f"  [dry-run] {os.path.basename(fp)} ({size / 1024:.1f} KB, {(now - mtime) / 86400:.0f} días)")
                else:
                    try:
                        os.remove(fp)
                        deleted += 1
                        freed += size
                    except OSError as e:
                        log(f"Error borrando {fp}: {e}")
            else:
                kept.append((mtime, size, fp))

        # 2. Si excede max archivos, borrar más viejos
        if len(kept) > MAX_FILES:
            kept.sort(key=lambda x: x[0])
            overflow = len(kept) - MAX_FILES
            for mtime, size, fp in kept[:overflow]:
                if dry_run:
                    log(f"  [dry-run] {os.path.basename(fp)} (por exceso de archivos)")
                else:
                    try:
                        os.remove(fp)
                        deleted += 1
                        freed += size
                    except OSError as e:
                        log(f"Error borrando {fp}: {e}")
            kept = kept[overflow:]

        # 3. Si excede tamaño máximo, borrar más viejos
        kept_size = sum(s for _, s, _ in kept)
        while len(kept) > 1 and kept_size > MAX_SIZE_BYTES:
            _, size, fp = kept.pop(0)
            if dry_run:
                log(f"  [dry-run] {os.path.basename(fp)} (por exceso de tamaño)")
            else:
                try:
                    os.remove(fp)
                    deleted += 1
                    freed += size
                except OSError as e:
                    log(f"Error borrando {fp}: {e}")
            kept_size -= size

        total_deleted += deleted
        total_freed += freed
        remaining = len(kept)
        remaining_size = sum(s for _, s, _ in kept)

        action = "[dry-run] " if dry_run else ""
        log(f"{action}{dir_path}: {before} → {deleted} borrados, {remaining} restantes ({remaining_size / 1024:.1f} KB)")

    if total_deleted == 0:
        log("Sin archivos por limpiar.")
    else:
        action = "[dry-run] " if dry_run else ""
        log(f"{action}Total: {total_deleted} archivos, {total_freed / 1024:.1f} KB liberados")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    cleanup(dry_run)
