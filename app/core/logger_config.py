import logging

# Configuración básica del logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Crear el logger principal
logger = logging.getLogger(__name__)

from app.utils.redaction import install_log_redaction
install_log_redaction()
