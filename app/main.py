
import os
import logging

from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# config.py o al inicio de main.py
from dotenv import load_dotenv

from .core.llm import create_llm
from .services.b2_service import B2Service

# Cargar variables de ambiente una sola vez
load_dotenv()


from .core.config import settings
from app.core.database import initialize_database
from .api.base_router import base_router
# from .db.database import engine
# from .db.database import Base
# from .db.models import *


app = FastAPI(
    title="Osai",
    description="""
### Osai


OSAI se encargará de simular el proceso humano de radicación, aplicando herramientas de inteligencia artificial que permiten analizar automáticamente archivos (PDFs, imágenes, escaneos), extraer su contenido (usando OCR o extractores como Tika o PyMuPDF), clasificar el tipo de documento (factura, contrato, solicitud, etc.) y generar respuestas estructuradas que integren con sistemas existentes de gestión documental.

#### Get Started 🚀
Follow these steps to register a new user and authenticate them successfully. Explore the API documentation below to see all available endpoints.
""",
    version="0.1.0",
)

# Configuración de CORS: restringir a los orígenes permitidos en producción
origins = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    os.environ.get("FRONTEND_URL", "http://localhost:9000"),
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# # Crear las tablas en la base de datos
# Base.metadata.create_all(bind=engine)

# --- INICIALIZACIÓN AUTOMÁTICA Y SEGURA ---
# Esto se ejecuta cada vez que se inicia el servidor/worker.
# Es seguro gracias a la idempotencia.
print(f"\n{'='*50}")
print(f"🚀 Iniciando aplicación OSAI")
print(f"🌍 Entorno: {settings.ENVIRONMENT}")
print(f"🤖 LLM Principal: {settings.AI_MODEL} ({settings.AI_PROVIDER})")
print(f"🆘 LLM Emergencia: {settings.AI_MODEL_EMERGENCY} ({settings.AI_PROVIDER_EMERGENCY})")
print(f"{'='*50}\n")

print("Verificando estado de la base de datos...")
initialize_database()

from app.utils.temp_cleaner import cleanup_stale_temp_files
cleanup_stale_temp_files(max_age_minutes=60) # Limpieza activa de basura en cada reinicio

print("✅ Inicialización completada. La aplicación está lista.\n")

app.include_router(base_router)

# Solo test ojo -> luego borrar
b2_service = B2Service()
bucket = b2_service.get_bucket()

# Endpoint de información general
@app.get("/info")
def read_root():
    return {
        "message": f" Hello, World! the app: {settings.APP_NAME} is Running in {settings.ENVIRONMENT} mode. bucket: {bucket.name}"} 

@app.get("/test")
def test_llm():
    llm = create_llm()
    response = llm.invoke("¿Cuál es el nombre de tu modelo?")
    return {"response": response}
