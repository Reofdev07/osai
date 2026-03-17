from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain.chat_models import init_chat_model

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



def create_llm():
    """
    Crea un objeto LLM dinámico basado en el AI_SELECTOR de settings.
    Soporta GEMINI, DEEPSEEK y COHERE.
    """
    provider = settings.AI_PROVIDER
    model = settings.AI_MODEL
    
    kwargs = {}
    if provider == "google_genai":
        kwargs["api_key"] = settings.GOOGLE_API_KEY
    elif provider == "deepseek":
        kwargs["api_key"] = settings.DEEPSEEK_API_KEY
    elif provider == "cohere":
        kwargs["api_key"] = settings.CO_API_KEY

    return init_chat_model(
        model, 
        model_provider=provider,
        rate_limiter=rate_limiter,
        max_retries=3, # Reintentos automáticos para manejar picos de tráfico
        **kwargs
    )

