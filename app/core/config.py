
import os
from pydantic_settings import BaseSettings
from functools import lru_cache

# Obtener el entorno PRIMERO. El valor por defecto es 'development'.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
print(ENVIRONMENT)

class Settings(BaseSettings):
    """Configuración base"""
    
    # App
    APP_NAME: str = "Osai"
    ENVIRONMENT: str = ENVIRONMENT # El valor se toma de la variable de entorno
    
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET")
    
    LANGSMITH_ENDPOINT: str = os.getenv("LANGSMITH_ENDPOINT")
    LANGSMITH_TRACING: bool = True
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT")
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY")
    
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    LLAMA_CLOUD_API_KEY: str = os.getenv("LLAMA_CLOUD_API_KEY")
        
    class Config:
        # Carga primero el .env y luego el específico del entorno.
        # Los valores de .env.development sobreescribirán los de .env si coinciden.
        env_file = (".env", f".env.{ENVIRONMENT}")
        extra = 'ignore' # Buena práctica para ignorar campos extra en los .env

class DevelopmentSettings(Settings):
    # Selector: GEMINI | DEEPSEEK | COHERE
    AI_SELECTOR: str = os.getenv("AI_SELECTOR", "GEMINI")

    # Claves originales de tu .env
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY")
    CO_API_KEY: str = os.getenv("CO_API_KEY")

    @property
    def AI_MODEL(self) -> str:
        mapping = {
            "GEMINI": os.getenv("MODEL_NAME_DEV") or "gemini-2.5-flash",
            "DEEPSEEK": "deepseek-chat",
            "COHERE": "command-r-plus"
        }
        return mapping.get(self.AI_SELECTOR, mapping["GEMINI"])

    @property
    def AI_PROVIDER(self) -> str:
        mapping = {
            "GEMINI": "google_genai",
            "DEEPSEEK": "deepseek",
            "COHERE": "cohere"
        }
        return mapping.get(self.AI_SELECTOR, mapping["GEMINI"])
    
    # Bucket
    BUCKET_NAME: str
    KEY_ID: str
    KEY_NAME: str
    APPLICATION_KEY: str
    
    class Config(Settings.Config):
        # Puedes sobreescribir la configuración si es necesario
        # pero heredando es suficiente en este caso.
        pass

class ProductionSettings(Settings):
    AI_MODEL: str = "gpt-4o"
    AI_PROVIDER: str = "openai"

    class Config(Settings.Config):
        pass

class TestingSettings(Settings):
    DATABASE_URL: str = "sqlite:///:memory:"
    AI_MODEL: str = "gpt-4o-mini"
    AI_PROVIDER: str = "openai"
    
    class Config(Settings.Config):
        # Para testing, a menudo no queremos leer ningún archivo .env
        env_file = None


@lru_cache()
def get_settings():
    # La lógica es más simple ahora. La clase Settings ya sabe qué archivo leer.
    if ENVIRONMENT == "production":
        return ProductionSettings()
    elif ENVIRONMENT == "testing":
        return TestingSettings()
    else:
        return DevelopmentSettings()

settings = get_settings()