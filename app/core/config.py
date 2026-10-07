import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# Cargar .env inicial
load_dotenv()

def positive_int_env(name: str, default: int) -> int:
    """Entero positivo del entorno. Vacío, no numérico, 0 o negativo NUNCA desactivan un tope: se usa el valor por defecto."""
    raw = os.getenv(name, "")
    try:
        value = int(str(raw).strip())
        if value > 0:
            return value
    except ValueError:
        pass
    if raw.strip():
        print(f"⚠️ {name}='{raw}' no es un entero positivo; se usa el valor por defecto {default}.")
    return default


def positive_float_env(name: str, default: float) -> float:
    """Decimal positivo del entorno; un valor inválido nunca desactiva el límite: se usa el valor por defecto."""
    raw = os.getenv(name, "")
    try:
        value = float(str(raw).strip())
        if value > 0:
            return value
    except ValueError:
        pass
    if raw.strip():
        print(f"⚠️ {name}='{raw}' no es un número positivo; se usa el valor por defecto {default}.")
    return default


def non_negative_int_env(name: str, default: int) -> int:
    """Entero >= 0 del entorno (0 = apagado). Vacío o inválido usa el valor por defecto."""
    raw = os.getenv(name, "")
    try:
        value = int(str(raw).strip())
        if value >= 0:
            return value
    except ValueError:
        pass
    if raw.strip():
        print(f"⚠️ {name}='{raw}' no es un entero válido; se usa el valor por defecto {default}.")
    return default


def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


class Settings(BaseSettings):
    """
    Configuración Unificada.
    Lee directamente del archivo .env principal.
    """
    
    # App
    APP_NAME: str = "Osai"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Worker de tareas en background (cola offline + webhook retry).
    # Con multiples workers uvicorn (--workers N) este flag debe estar activo
    # SOLO en una instancia para evitar procesamiento duplicado.
    BACKGROUND_WORKER: bool = os.getenv("BACKGROUND_WORKER", "true").lower() in ("1", "true", "yes", "on")
    
    # Webhook
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL")
    PORTAL_WEBHOOK_URL: str = os.getenv("PORTAL_WEBHOOK_URL", "")
    
    # Langsmith
    LANGSMITH_ENDPOINT: str = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    LANGSMITH_TRACING: bool = False
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "Osai")
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
    
    # Claves Externas
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    # Selectores IA
    AI_SELECTOR: str = os.getenv("AI_SELECTOR", "GEMINI")
    AI_SELECTOR_EMERGENCY: str = os.getenv("AI_SELECTOR_EMERGENCY", "GEMINI")
    
    AI_SELECTOR_VISION: str = os.getenv("AI_SELECTOR_VISION", "GEMINI")

    # Cadenas de proveedores (orden = prioridad). Un proveedor sin API key se omite con aviso.
    # Texto (análisis, chat) y visión: deepseek -> gemini -> openai.
    TEXT_CHAIN: str = os.getenv("TEXT_CHAIN", "deepseek,gemini,openai")
    VISION_CHAIN: str = os.getenv("VISION_CHAIN", "deepseek,gemini,openai")
    # Respaldo OCR clásico (Google Cloud Vision) tras agotar la cadena de visión. Apagado por defecto (sin OCR).
    VISION_GOOGLE_OCR_FALLBACK: bool = os.getenv("VISION_GOOGLE_OCR_FALLBACK", "false").lower() in ("1", "true", "yes", "on")

    # Topes de seguridad del archivo (anti-DoS). Excedidos -> el documento termina con error claro.
    MAX_PDF_PAGES: int = positive_int_env("MAX_PDF_PAGES", 60)
    MAX_IMAGE_PIXELS: int = positive_int_env("MAX_IMAGE_PIXELS", 25000000)
    MAX_DOWNLOAD_MB: int = positive_int_env("MAX_DOWNLOAD_MB", 100)

    # Rendimiento (fase 2). Todo con valores por defecto seguros.
    OSAI_CPU_THREADS: int = positive_int_env("OSAI_CPU_THREADS", 4)               # hilos para trabajo pesado fuera del event loop
    VISION_PAGE_CONCURRENCY: int = positive_int_env("VISION_PAGE_CONCURRENCY", 3) # páginas en visión a la vez por documento
    VISION_DPI: int = positive_int_env("VISION_DPI", 150)
    VISION_JPEG_QUALITY: int = min(positive_int_env("VISION_JPEG_QUALITY", 85), 100)
    VISION_429_RETRIES: int = non_negative_int_env("VISION_429_RETRIES", 2)       # esperas/reintentos ante 429 por proveedor
    VISION_429_WAIT_SECONDS: float = positive_float_env("VISION_429_WAIT_SECONDS", 5.0)
    LLM_RATE_LIMIT_RPS: float = positive_float_env("LLM_RATE_LIMIT_RPS", 1.0)     # peticiones por segundo a los LLM (por proceso)
    TEXT_PAGE_MIN_CHARS: int = positive_int_env("TEXT_PAGE_MIN_CHARS", 50)        # texto mínimo para considerar digital una página
    PDF_SKIP_MARKITDOWN: bool = bool_env("PDF_SKIP_MARKITDOWN", True)             # PDF con texto en todas sus páginas: usar PyMuPDF
    # Caché del texto extraído por visión, por sha256 del archivo. EXTRACT_CACHE_DAYS=0 la apaga.
    EXTRACT_CACHE_DAYS: int = non_negative_int_env("EXTRACT_CACHE_DAYS", 7)
    EXTRACT_CACHE_MAX_MB: int = positive_int_env("EXTRACT_CACHE_MAX_MB", 200)
    EXTRACT_CACHE_DIR: str = os.getenv("EXTRACT_CACHE_DIR", "") or "data/extract_cache"

    # Claves API IA
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    CO_API_KEY: str = os.getenv("CO_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Versiones de Modelos (Configurables en .env)
    MODEL_GEMINI: str = os.getenv("MODEL_GEMINI", "gemini-2.5-flash")
    MODEL_DEEPSEEK: str = os.getenv("MODEL_DEEPSEEK", "deepseek-flash")
    MODEL_COHERE: str = os.getenv("MODEL_COHERE", "command-r-plus")
    # OPENAI: confirmar el id exacto del modelo (p. ej. GPT-5.6 Luna) en la consola de OpenAI y fijarlo en MODEL_OPENAI.
    MODEL_OPENAI: str = os.getenv("MODEL_OPENAI", "gpt-4o")
    # DeepSeek V4.1 Flash (multimodal) para la cadena de visión.
    MODEL_DEEPSEEK_VISION: str = os.getenv("MODEL_DEEPSEEK_VISION", "deepseek-flash")
    MODEL_OPENAI_VISION: str = os.getenv("MODEL_OPENAI_VISION", "") or os.getenv("MODEL_OPENAI", "gpt-4o")
    MODEL_GEMINI_VISION: str = os.getenv("MODEL_GEMINI_VISION", "") or os.getenv("MODEL_GEMINI", "gemini-2.5-flash")

    # Mappings de Modelos dinámico
    @property
    def _MODEL_MAP(self) -> dict:
        return {
            "GEMINI": self.MODEL_GEMINI,
            "DEEPSEEK": self.MODEL_DEEPSEEK,
            "COHERE": self.MODEL_COHERE,
            "OPENAI": self.MODEL_OPENAI
        }

    _PROVIDER_MAP: dict = {
        "GEMINI": "google_genai",
        "DEEPSEEK": "deepseek",
        "COHERE": "cohere",
        "OPENAI": "openai"
    }

    # Modelo Principal
    @property
    def AI_MODEL(self) -> str:
        custom = os.getenv("MODEL_NAME")
        if custom: return custom
        return self._MODEL_MAP.get(self.AI_SELECTOR, self._MODEL_MAP["GEMINI"])

    @property
    def AI_PROVIDER(self) -> str:
        return self._PROVIDER_MAP.get(self.AI_SELECTOR, self._PROVIDER_MAP["GEMINI"])

    # Modelo de Emergencia
    @property
    def AI_MODEL_EMERGENCY(self) -> str:
        return self._MODEL_MAP.get(self.AI_SELECTOR_EMERGENCY, self._MODEL_MAP["GEMINI"])

    @property
    def AI_PROVIDER_EMERGENCY(self) -> str:
        return self._PROVIDER_MAP.get(self.AI_SELECTOR_EMERGENCY, self._PROVIDER_MAP["GEMINI"])

    # Modelo de Visión
    @property
    def AI_MODEL_VISION(self) -> str:
        return self._MODEL_MAP.get(self.AI_SELECTOR_VISION, self._MODEL_MAP["GEMINI"])

    @property
    def AI_PROVIDER_VISION(self) -> str:
        return self._PROVIDER_MAP.get(self.AI_SELECTOR_VISION, self._PROVIDER_MAP["GEMINI"])

    # Bucket B2
    BUCKET_NAME: str = os.getenv("BUCKET_NAME", "")
    KEY_ID: str = os.getenv("KEY_ID", "")
    KEY_NAME: str = os.getenv("KEY_NAME", "")
    APPLICATION_KEY: str = os.getenv("APPLICATION_KEY", "")

    # Backend URL (Laravel SGD)
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

    # SSRF: sufijos de host permitidos para descargar archivos (separados por coma)
    # Ej: backblazeb2.com,s3.amazonaws.com,contabo.com
    ALLOWED_DOWNLOAD_HOSTS: str = os.getenv("ALLOWED_DOWNLOAD_HOSTS", "")

    # API Tokens para endpoints protegidos
    @property
    def API_TOKENS(self) -> set:
        token_str = os.getenv("API_KEY_TOKEN", "")
        if token_str:
            return {t.strip() for t in token_str.split(",") if t.strip()}
        return set()

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()