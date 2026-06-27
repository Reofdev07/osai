# Stage 1: Builder - Instala dependencias en un entorno de compilación
FROM python:3.11-slim as builder

# Establecer el directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema operativo
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Crear un entorno virtual
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiar solo el archivo de requerimientos para aprovechar el cache de Docker
COPY requirements.txt .

# Instalar las dependencias en el entorno virtual
# Usamos --no-cache-dir para reducir el tamaño de la imagen
# Timeouts muy largos y muchos reintentos para redes inestables
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=30
RUN pip install --no-cache-dir --upgrade pip
# Instalar en lotes muy pequeños con --prefer-binary (descarga wheels directos)
# Si un lote falla por timeout, los anteriores quedan cacheados
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    fastapi uvicorn[standard] pydantic pydantic-settings python-dotenv python-multipart
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    langchain langchain-core
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    langchain-community langchain-openai
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    langchain-google-genai langchain-google-community langchain-cohere langchain-deepseek
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    langgraph langgraph-checkpoint-sqlite langsmith aiosqlite
RUN for i in $(seq 1 10); do \
        pip install --no-cache-dir --retries 10 --prefer-binary markitdown 2>&1 && break; \
        echo "=== Intento $i/10 falló, reintentando en 15s... ==="; \
        sleep 15; \
    done
RUN for i in $(seq 1 10); do \
        pip install --no-cache-dir --retries 10 --prefer-binary openai 2>&1 && break; \
        echo "=== Intento $i/10 falló, reintentando en 15s... ==="; \
        sleep 15; \
    done
RUN for i in $(seq 1 10); do \
        pip install --no-cache-dir --retries 10 --prefer-binary tiktoken 2>&1 && break; \
        echo "=== Intento $i/10 falló, reintentando en 15s... ==="; \
        sleep 15; \
    done
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    google-cloud-vision python-magic puremagic PyMuPDF pypdf
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    beautifulsoup4 striprtf nltk python-docx openpyxl tabulate
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    "sqlalchemy>=2.0.0,<2.1" b2sdk sentry-sdk httpx numpy pandas
RUN pip install --no-cache-dir --retries 30 --prefer-binary \
    tenacity tqdm nest-asyncio

# Stage 2: Runner - La imagen final y ligera
FROM python:3.11-slim

# Instalar libmagic1 y curl en tiempo de ejecución
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Establecer el directorio de trabajo
WORKDIR /app

# Crear un usuario no-root para mayor seguridad
RUN useradd --create-home --shell /bin/bash appuser

# Copiar el entorno virtual con las dependencias desde la etapa 'builder'
COPY --from=builder /opt/venv /opt/venv

# Copiar el código de la aplicación
COPY ./app ./app

# Crear directorios de persistencia y credenciales con permisos
RUN mkdir -p /app/data /app/credentials

# Cambiar el propietario de los archivos al usuario no-root
RUN chown -R appuser:appuser /app

# Cambiar al usuario no-root
USER appuser

# Hacer que el entorno virtual sea el intérprete de Python por defecto
ENV PATH="/opt/venv/bin:$PATH"

# Exponer el puerto en el que correrá la aplicación
EXPOSE 8000

# Comando para iniciar la aplicación con Uvicorn
# Usamos --host 0.0.0.0 para que sea accesible desde fuera del contenedor
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
