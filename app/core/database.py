import sqlite3
from datetime import datetime
import os

# --- Ubicación centralizada del archivo de la base de datos ---
# Esto asegura que todo el código use la misma ruta.
# Se creará en un subdirectorio 'data' para mantener el proyecto limpio.
DATA_DIR = "data"
DB_FILE = os.path.join(DATA_DIR, "app_state.db")

def initialize_database():
    """
    Función idempotente para inicializar la base de datos.
    Se puede llamar de forma segura cada vez que se inicia la aplicación.
    """
    try:
        # Asegurarse de que el directorio de datos exista
        os.makedirs(DATA_DIR, exist_ok=True)
        
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # 1. Crear la tabla de configuración si no existe.
            # Esta operación es segura y no hará nada si la tabla ya está creada.
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """)
            
            # 2. Insertar valores iniciales si no existen.
            # "INSERT OR IGNORE" es la clave para la seguridad: solo inserta si la 'key' no existe.
            # No sobrescribirá el contador actual si la aplicación se reinicia.
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                           ("llama_parse_usage", "0"))
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                           ("google_vision_usage", "0"))
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", 
                           ("llama_parse_reset_timestamp", datetime.now().isoformat()))
            
            conn.commit()
            print(f"Base de datos '{DB_FILE}' verificada y lista.")
            
    except sqlite3.Error as e:
        print(f"CRITICAL: Error al inicializar o verificar la base de datos: {e}")
        # En un entorno de producción real, podrías querer que la aplicación falle aquí
        # si la base de datos no es accesible.
        raise e