
import os
import logging

from fastapi import FastAPI, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# config.py o al inicio de main.py
from dotenv import load_dotenv

from .core.llm import create_llm

# Cargar variables de ambiente una sola vez
load_dotenv()


from .core.config import settings
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
    "http://127.0.0.1:8000/",
    # "http://18.189.100.75",
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

app.include_router(base_router)

# Endpoint de información general
@app.get("/info")
def read_root():
    return {
        "message": f" Hello, World! the app: {settings.APP_NAME} is Running in {settings.ENVIRONMENT} mode."}

@app.get("/test")
def test_llm():
    llm = create_llm()
    response = llm.invoke("¿Cuál es el nombre de tu modelo?")
    return {"response": response}
