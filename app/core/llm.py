from langchain.chat_models import init_chat_model

from dotenv import load_dotenv

from app.core.config import settings


load_dotenv()



def create_llm():
    """
    Crea un objeto llamado LLM que se encarga de generar respuestas a partir de un modelo de lenguaje.
    Utiliza la configuración del entorno para determinar qué modelo y proveedor usar.

    Returns:
        LLM: Instancia de LLM.
    """
    # nota add **kwargs de ser necesario
    # para pasar más parámetros al modelo
    # return init_chat_model(
    #     settings.AI_MODEL, model_provider=settings.AI_PROVIDER
    # )
    return init_chat_model(
        model="command-r-08-2024", 
        model_provider="cohere",
    )
