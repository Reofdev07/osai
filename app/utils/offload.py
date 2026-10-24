"""Trabajo pesado y síncrono (MarkItDown, PyMuPDF, PIL, hashing, tiktoken) fuera del event loop.

Un ThreadPoolExecutor acotado (OSAI_CPU_THREADS) evita que un escaneado grande congele el chat, el health y los webhooks.
"""
import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=settings.OSAI_CPU_THREADS, thread_name_prefix="osai-cpu")
    return _executor


async def run_cpu(fn, *args, **kwargs):
    """Ejecuta fn(*args, **kwargs) en el pool acotado sin bloquear el loop. Las excepciones se propagan igual."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), functools.partial(fn, *args, **kwargs))
