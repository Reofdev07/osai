"""Cadena de proveedores de LLM (texto y visión) configurable por entorno.

TEXT_CHAIN / VISION_CHAIN = lista de proveedores en orden de prioridad (claude, deepseek, gemini, openai; cohere solo texto).
Un proveedor sin API key se omite con un aviso. Los fallos se registran sin datos del documento.
"""
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain.chat_models import init_chat_model

from dotenv import load_dotenv

from app.core.config import settings


load_dotenv()

# Configuración de Rate Limiter (Gemini Free: 15 RPM -> 1 peticion cada 4 segs)
# Esto permite paralelizacion en el grafo sin bloquear el API.
rate_limiter = InMemoryRateLimiter(
    requests_per_second=settings.LLM_RATE_LIMIT_RPS,  # LLM_RATE_LIMIT_RPS (1.0 por defecto)
    check_every_n_seconds=0.1, 
    max_bucket_size=2 # Aumentado para permitir ráfagas pequeñas iniciales
)

# nombre en la cadena -> (proveedor LangChain, atributo de la API key)
_PROVIDERS = {
    "deepseek": ("deepseek", "DEEPSEEK_API_KEY"),
    "openai": ("openai", "OPENAI_API_KEY"),
    "gemini": ("google_genai", "GOOGLE_API_KEY"),
    "cohere": ("cohere", "CO_API_KEY"),
    "claude": ("anthropic", "ANTHROPIC_API_KEY"),
}
_VISION_PROVIDERS = {"deepseek", "openai", "gemini", "claude"}


def _model_name(name: str, vision: bool) -> str:
    if vision:
        return {
            "deepseek": settings.MODEL_DEEPSEEK_VISION,
            "openai": settings.MODEL_OPENAI_VISION,
            "gemini": settings.MODEL_GEMINI_VISION,
            "claude": settings.MODEL_CLAUDE_VISION,
        }[name]
    return {
        "deepseek": settings.MODEL_DEEPSEEK,
        "openai": settings.MODEL_OPENAI,
        "gemini": settings.MODEL_GEMINI,
        "cohere": settings.MODEL_COHERE,
        "claude": settings.MODEL_CLAUDE,
    }[name]


def chain_providers(chain: str, vision: bool = False) -> list[str]:
    """Proveedores de la cadena que se pueden usar (con API key). Los demás se omiten con aviso en el log."""
    usable = []
    for raw in (chain or "").split(","):
        name = raw.strip().lower()
        if not name:
            continue
        if name not in _PROVIDERS or (vision and name not in _VISION_PROVIDERS):
            print(f"⚠️ LLM: proveedor '{name}' no válido para la cadena {'de visión' if vision else 'de texto'}; se omite.")
            continue
        if not getattr(settings, _PROVIDERS[name][1], ""):
            print(f"⚠️ LLM: proveedor '{name}' sin API key; se omite de la cadena.")
            continue
        usable.append(name)
    return usable


def _form_kwargs(provider: str, structured: bool) -> dict:
    """
    Llamadas que piden un formulario fijo (with_structured_output): en DeepSeek se apaga el modo de pensamiento,
    que no admite la herramienta obligatoria. El chat y el texto libre no pasan por aquí.
    """
    kwargs: dict = {}
    if provider == "anthropic":
        # Sin tope la librería pide el máximo de salida del modelo, que el SDK rechaza en llamadas sin streaming.
        kwargs["max_tokens"] = settings.CLAUDE_MAX_TOKENS
        if structured and settings.CLAUDE_THINKING_FOR_FORMS.strip().lower() != "enabled":
            kwargs["thinking"] = {"type": "disabled"}
    if structured and provider == "deepseek" and settings.DEEPSEEK_THINKING_FOR_FORMS.strip().lower() != "enabled":
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return kwargs


def build_provider_llm(name: str, vision: bool = False, structured: bool = False):
    provider, key_attr = _PROVIDERS[name]
    return init_chat_model(
        _model_name(name, vision),
        model_provider=provider,
        rate_limiter=rate_limiter,
        max_retries=2,
        timeout=180,
        api_key=getattr(settings, key_attr),
        **_form_kwargs(provider, structured),
    )


def create_llm(provider: str = None, model: str = None, structured: bool = True):
    """
    Crea un objeto LLM. Con argumentos usa ese proveedor/modelo; sin argumentos devuelve el
    principal de TEXT_CHAIN (compatible con bind_tools, astream y with_structured_output).
    Lo usa el análisis de documentos (formulario fijo): structured=True por defecto.
    """
    if provider or model:
        selected_provider = provider or settings.AI_PROVIDER
        selected_model = model or settings.AI_MODEL
        key_attr = {"google_genai": "GOOGLE_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
                    "cohere": "CO_API_KEY", "openai": "OPENAI_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY"}.get(selected_provider)
        kwargs = {"api_key": getattr(settings, key_attr)} if key_attr else {}
        kwargs.update(_form_kwargs(selected_provider, structured))
        return init_chat_model(
            selected_model,
            model_provider=selected_provider,
            rate_limiter=rate_limiter,
            max_retries=2,
            timeout=180,
            **kwargs
        )
    return text_chain_llms(structured=structured)[0]


def text_chain_llms(structured: bool = False) -> list:
    """Modelos de texto en orden de prioridad (solo proveedores con API key). structured: piden un formulario fijo."""
    names = chain_providers(settings.TEXT_CHAIN)
    if not names:
        raise RuntimeError("TEXT_CHAIN no tiene ningún proveedor con API key configurada.")
    return [build_provider_llm(n, structured=structured) for n in names]


def _log_failure(label: str, index: int, total: int, exc: Exception) -> None:
    # Solo el tipo de error: el mensaje podría incluir fragmentos del documento o URLs.
    siguiente = "pasando al siguiente" if index < total - 1 else "sin más respaldos"
    print(f"⚠️ LLM {label}: proveedor {index + 1}/{total} falló ({type(exc).__name__}); {siguiente}.")


class _LoggedChain:
    """Ejecuta los runnables en orden: si uno falla registra el fallo y pasa al siguiente."""

    def __init__(self, runnables: list, label: str):
        self.runnables = runnables
        self.label = label

    async def ainvoke(self, *args, **kwargs):
        last = None
        for i, r in enumerate(self.runnables):
            try:
                return await r.ainvoke(*args, **kwargs)
            except Exception as exc:
                last = exc
                _log_failure(self.label, i, len(self.runnables), exc)
        raise last

    async def astream(self, *args, **kwargs):
        last = None
        for i, r in enumerate(self.runnables):
            emitted = False
            try:
                async for chunk in r.astream(*args, **kwargs):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:
                if emitted:
                    raise  # ya se envió texto al cliente: no se puede reiniciar a mitad de respuesta
                last = exc
                _log_failure(self.label, i, len(self.runnables), exc)
        raise last


class FallbackLLM:
    """Cadena de modelos de texto con respaldo: with_structured_output / ainvoke / astream pasan al siguiente si uno falla."""

    def __init__(self, models: list, label: str = "texto"):
        self.models = models
        self.label = label

    def with_structured_output(self, schema, **kwargs):
        return _LoggedChain([m.with_structured_output(schema, **kwargs) for m in self.models], self.label)

    async def ainvoke(self, *args, **kwargs):
        return await _LoggedChain(self.models, self.label).ainvoke(*args, **kwargs)

    def astream(self, *args, **kwargs):
        return _LoggedChain(self.models, self.label).astream(*args, **kwargs)


def create_llm_chain(structured: bool = False) -> FallbackLLM:
    """Cadena completa de texto (principal + respaldos). structured=True si se pide un formulario fijo."""
    return FallbackLLM(text_chain_llms(structured=structured))


def create_llm_emergency():
    """
    Respaldo de texto: los proveedores de TEXT_CHAIN tras el principal. Se usa si el principal falla
    después de reintentos. Con un solo proveedor configurado, reintenta con ese mismo.
    """
    models = text_chain_llms(structured=True)  # solo lo usa el análisis de documentos (formulario fijo)
    return FallbackLLM(models[1:] or models, "emergencia")


def vision_chain() -> list[tuple[str, object]]:
    """[(nombre, modelo)] de visión en orden de prioridad (solo proveedores multimodales con API key)."""
    names = chain_providers(settings.VISION_CHAIN, vision=True)
    if not names:
        raise RuntimeError("VISION_CHAIN no tiene ningún proveedor multimodal con API key configurada.")
    return [(n, build_provider_llm(n, vision=True)) for n in names]
