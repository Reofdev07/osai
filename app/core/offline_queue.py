"""
Módulo de cola offline para procesamiento de documentos con IA.
Procesa jobs pendientes cuando la conexión con el backend se recupera.
"""

import asyncio
import logging
from datetime import datetime
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)

MAX_CONCURRENT_JOBS = 3
MAX_RETRIES = 5
RETRY_DELAYS = [30, 60, 120, 300, 600]  # segundos


async def add_pending_job(job_id: str, document_id: int, file_url: str) -> None:
    """Agrega un job a la cola pendiente para procesamiento posterior."""
    try:
        with get_db_connection() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO pending_ai_jobs (id, document_id, file_url, status, created_at)
                   VALUES (?, ?, ?, 'pending', ?)""",
                (job_id, document_id, file_url, datetime.now().isoformat()),
            )
            conn.commit()
        logger.info(f"Job pendiente agregado: {job_id} (doc {document_id})")
    except Exception as e:
        logger.error(f"Error al agregar job pendiente {job_id}: {e}")


async def mark_job_completed(job_id: str) -> None:
    """Marca un job como completado."""
    try:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE pending_ai_jobs SET status = 'completed' WHERE id = ?",
                (job_id,),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error al marcar job {job_id} como completado: {e}")


async def mark_job_failed(job_id: str, error_message: str) -> None:
    """Marca un job como fallido con mensaje de error."""
    try:
        with get_db_connection() as conn:
            conn.execute(
                """UPDATE pending_ai_jobs
                   SET status = 'failed', last_error = ?, retry_count = retry_count + 1
                   WHERE id = ?""",
                (error_message, job_id),
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error al marcar job {job_id} como fallido: {e}")


async def get_pending_jobs(limit: int = MAX_CONCURRENT_JOBS):
    """Obtiene jobs pendientes que no han excedido el máximo de reintentos."""
    try:
        with get_db_connection() as conn:
            conn.row_factory = None  # Usar tuplas
            cursor = conn.execute(
                """SELECT id, document_id, file_url, retry_count
                   FROM pending_ai_jobs
                   WHERE status = 'pending' AND retry_count < ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (MAX_RETRIES, limit),
            )
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error al obtener jobs pendientes: {e}")
        return []


async def process_pending_jobs():
    """
    Procesa jobs de IA pendientes en background.
    Se ejecuta como tarea asíncrona en el startup de la aplicación.
    No procesa más de MAX_CONCURRENT_JOBS simultáneamente para no saturar la API de LLM.
    """
    from app.utils.util import stream_download_file

    logger.info("Iniciando worker de cola offline para jobs de IA...")

    while True:
        try:
            pending = await get_pending_jobs()
            if not pending:
                await asyncio.sleep(30)
                continue

            logger.info(f"Procesando {len(pending)} job(s) pendiente(s) de IA...")

            tasks = []
            for job_id, document_id, file_url, retry_count in pending:
                if retry_count == 0:
                    delay = 0
                else:
                    delay_idx = min(retry_count - 1, len(RETRY_DELAYS) - 1)
                    delay = min(RETRY_DELAYS[delay_idx], 1800)
                task = asyncio.create_task(_process_single_job(job_id, document_id, file_url, delay))
                tasks.append(task)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Error en el worker de cola offline: {e}")
            await asyncio.sleep(60)

        await asyncio.sleep(10)


async def _process_single_job(job_id: str, document_id: int, file_url: str, delay: int) -> None:
    """Procesa un job individual con reintento."""
    from app.utils.util import stream_download_file

    logger.info(f"Procesando job {job_id} (doc {document_id}, delay {delay}s)...")

    try:
        await asyncio.sleep(delay)
        await stream_download_file(file_url, job_id)
        await mark_job_completed(job_id)
        logger.info(f"Job {job_id} completado exitosamente.")
    except Exception as e:
        error_msg = str(e)[:500]
        await mark_job_failed(job_id, error_msg)
        logger.error(f"Job {job_id} falló: {error_msg}")
