from langchain.chat_models import init_chat_model

from dotenv import load_dotenv

from app.core.config import settings


load_dotenv()



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
        **kwargs
    )

