from fastapi import APIRouter

from .document_analyze.doc_analyze_router import doc_analyze_router
from .document_analyze.portal_analyze_router import portal_router
from .public_pqrsd.router import pqrsd_router

base_router = APIRouter(
    prefix="/api",
)

routers = [
    doc_analyze_router,
    portal_router,
    pqrsd_router,
]

for router in routers:
    base_router.include_router(router)
