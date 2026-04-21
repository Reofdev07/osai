import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from functools import lru_cache

# Cargar .env inicial
load_dotenv()

class Settings(BaseSettings):
    """
    Configuración Unificada.
    Lee directamente del archivo .env principal.
    """
    
    # App
    APP_NAME: str = "Osai"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Webhook
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL")
    
    # Langsmith
    LANGSMITH_ENDPOINT: str = os.getenv("LANGSMITH_ENDPOINT")
    LANGSMITH_TRACING: bool = True
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT")
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY")
    
    # Claves Externas
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    LLAMA_CLOUD_API_KEY: str = os.getenv("LLAMA_CLOUD_API_KEY")

    # Selectores IA
    AI_SELECTOR: str = os.getenv("AI_SELECTOR", "GEMINI")
    AI_SELECTOR_EMERGENCY: str = os.getenv("AI_SELECTOR_EMERGENCY", "GEMINI")

    # Claves API IA
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    CO_API_KEY: str = os.getenv("CO_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Mappings de Modelos
    _MODEL_MAP: dict = {
        "GEMINI": "gemini-2.5-flash",
        "DEEPSEEK": "deepseek-chat",
        "COHERE": "command-r-plus",
        "OPENAI": "gpt-4o"
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

    # Bucket B2
    BUCKET_NAME: str = os.getenv("BUCKET_NAME", "")
    KEY_ID: str = os.getenv("KEY_ID", "")
    KEY_NAME: str = os.getenv("KEY_NAME", "")
    APPLICATION_KEY: str = os.getenv("APPLICATION_KEY", "")

    class Config:
        env_file = ".env"
        extra = 'ignore'


@lru_cache()
def get_settings():
    return Settings()

settings = get_settings()