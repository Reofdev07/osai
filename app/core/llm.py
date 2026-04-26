from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI

from dotenv import load_dotenv

from app.core.config import settings


load_dotenv()

# Configuración de Rate Limiter (Gemini Free: 15 RPM -> 1 peticion cada 4 segs)
# Esto permite paralelizacion en el grafo sin bloquear el API.
rate_limiter = InMemoryRateLimiter(
    requests_per_second=1.0, # Aumentado de 0.25 a 1.0 para mayor velocidad (1 peticion/seg)
    check_every_n_seconds=0.1, 
    max_bucket_size=2 # Aumentado para permitir ráfagas pequeñas iniciales
)



def create_llm(provider: str = None, model: str = None):
    """
    Crea un objeto LLM. Si no se pasan argumentos, usa lo configurado en el .env.
    """
    selected_provider = provider or settings.AI_PROVIDER
    selected_model = model or settings.AI_MODEL
    
    kwargs = {}
    if selected_provider == "google_genai":
        kwargs["api_key"] = settings.GOOGLE_API_KEY
    elif selected_provider == "deepseek":
        kwargs["api_key"] = settings.DEEPSEEK_API_KEY
    elif selected_provider == "cohere":
        kwargs["api_key"] = settings.CO_API_KEY
    elif selected_provider == "openai":
        kwargs["api_key"] = settings.OPENAI_API_KEY

    return init_chat_model(
        selected_model, 
        model_provider=selected_provider,
        rate_limiter=rate_limiter,
        max_retries=2,
        **kwargs
    )


def create_llm_emergency():
    """
    Crea el LLM de emergencia usando AI_SELECTOR_EMERGENCY del .env.
    Se usa automáticamente si el modelo principal falla después de reintentos.
    """
    return create_llm(
        provider=settings.AI_PROVIDER_EMERGENCY,
        model=settings.AI_MODEL_EMERGENCY
    )


def create_llm_vision():
    """LLM dedicado para tareas de visión (OCR multimodal)."""
    return create_llm(
        provider=settings.AI_PROVIDER_VISION,
        model=settings.AI_MODEL_VISION
    )


def create_llm_vision_fallback():
    """
    LLM de respaldo para visión: vía OpenRouter.
    Permite acceso a la variante gratuita de Qwen u otras ultrabaratas.
    """
    return ChatOpenAI(
        model=settings.AI_MODEL_VISION_FALLBACK,
        openai_api_base="https://openrouter.ai/api/v1",
        openai_api_key=settings.OPENROUTER_API_KEY,
        max_retries=2,
        rate_limiter=rate_limiter
    )

