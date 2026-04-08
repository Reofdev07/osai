import os
import time
import tempfile
import glob

def cleanup_stale_temp_files(max_age_minutes: int = 60):
    """
    Elimina archivos temporales en el directorio del sistema
    que tengan más de max_age_minutes de antigüedad.
    Ayuda a mantener el servidor limpio en caso de caídas inesperadas.
    """
    print("🧹 Iniciando limpieza de archivos temporales huérfanos...")
    # Usamos el directorio temporal por defecto del sistema
    temp_dir = tempfile.gettempdir()
    
    # Extensiones de archivos temporales manejados por OSAI
    pattern_extensions = ["*.tmp", "*.pdf", "*.png", "*.jpg", "*.jpeg"]
    
    current_time = time.time()
    max_age_seconds = max_age_minutes * 60
    deleted_files = []
    
    for ext in pattern_extensions:
        # Busca solo archivos que empiecen con 'osai_' para evitar tocar archivos ajenos
        search_path = os.path.join(temp_dir, f"osai_{ext}")
        for filepath in glob.glob(search_path):
            try:
                # Verificar el tiempo de la última modificación
                file_age = current_time - os.path.getmtime(filepath)
                if file_age > max_age_seconds:
                    os.remove(filepath)
                    deleted_files.append(filepath)
            except Exception as e:
                print(f"⚠️ Aviso: No se pudo limpiar el archivo {filepath}: {e}")
                
    deleted_count = len(deleted_files)
    if deleted_count > 0:
        print(f"✅ Limpieza completada: Se eliminaron {deleted_count} archivos antiguos.")
    else:
        print("✅ Limpieza completada: El disco ya estaba limpio (0 archivos borrados).")

    # --- Limpieza de webhooks pendientes con más de 24 horas ---
    webhook_dir = os.path.join("data", "pending_webhooks")
    if os.path.exists(webhook_dir):
        webhook_deleted_files = []
        for filepath in glob.glob(os.path.join(webhook_dir, "*.json")):
            try:
                if (current_time - os.path.getmtime(filepath)) > 86400:  # 24 horas
                    os.remove(filepath)
                    webhook_deleted_files.append(filepath)
            except Exception:
                pass
        
        webhook_deleted = len(webhook_deleted_files)
        if webhook_deleted > 0:
            print(f"✅ Webhooks pendientes limpiados: {webhook_deleted} archivos eliminados (>24h).")
