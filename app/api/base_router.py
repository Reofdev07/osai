from fastapi import APIRouter

from .document_analyze.doc_analyze_router import doc_analyze_router

base_router = APIRouter(
    prefix="/api",
)

routers = [
    doc_analyze_router,
]

for router in routers:
    base_router.include_router(router)
