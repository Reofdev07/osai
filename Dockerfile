# Stage 1: Builder - Instala dependencias en un entorno de compilación
FROM python:3.11-slim as builder

# Establecer el directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema operativo si fueran necesarias (ej. para compilar paquetes)
# RUN apt-get update && apt-get install -y --no-install-recommends gcc build-essential

# Crear un entorno virtual
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiar solo el archivo de requerimientos para aprovechar el cache de Docker
COPY requirements.txt .

# Instalar las dependencias en el entorno virtual
# Usamos --no-cache-dir para reducir el tamaño de la imagen
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Runner - La imagen final y ligera
FROM python:3.11-slim

# Establecer el directorio de trabajo
WORKDIR /app

# Crear un usuario no-root para mayor seguridad
RUN useradd --create-home --shell /bin/bash appuser

# Copiar el entorno virtual con las dependencias desde la etapa 'builder'
COPY --from=builder /opt/venv /opt/venv

# Copiar el código de la aplicación
COPY ./app ./app

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
