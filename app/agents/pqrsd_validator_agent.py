from langchain_core.messages import HumanMessage, SystemMessage
from app.core.llm import create_llm
from app.schemas.agent_schemas import PqrsdValidationOutput


async def pqrsd_validator_agent(payload: dict) -> dict:
    """
    Agent that analyzes a citizen's PQRSD payload (subject, description, location)
    and returns a structured PqrsdValidationOutput JSON.
    """
    llm = create_llm()
    
    # We use LangChain's with_structured_output to force the LLM to output the exact JSON structure
    structured_llm = llm.with_structured_output(PqrsdValidationOutput, include_raw=True)

    # Compile the incoming text from the public portal
    subject = payload.get("subject", "")
    description = payload.get("description", "")
    location = payload.get("location", "")
    
    citizen_input = (
        f"Asunto: {subject}\n"
        f"Descripción: {description}\n"
        f"Ubicación: {location}"
    )

    system_prompt = (
        "Eres un experto en gestión documental y normatividad pública colombiana (Ley 1755). "
        "Tu tarea es pre-analizar solicitudes ciudadanas (PQRSD) antes de que entren a la ventanilla oficial.\n\n"
        "REGLAS DE CLASIFICACIÓN:\n"
        "- Petición: Pide documentos, copias, o realizar un trámite.\n"
        "- Queja: Inconformidad contra el comportamiento de un funcionario.\n"
        "- Reclamo: Inconformidad por un servicio público mal prestado (ej. basuras, huecos, luz).\n"
        "- Sugerencia: Propuesta de mejora.\n"
        "- Denuncia: Reporte de un delito o acto de corrupción.\n\n"
        "REGLAS DE CONTEXTO:\n"
        "- Para que el status sea 'Cumple', la solicitud debe ser inteligible y dar contexto "
        "mínimo de QUÉ quiere y POR QUÉ o DÓNDE (ej. 'Hay un hueco en la calle 10').\n"
        "- Si el texto no tiene sentido (ej. 'asdf'), o si es muy ambiguo ('necesito que arreglen la calle', pero "
        "no dice cuál calle, o municipio), el status debe ser 'Incompleto_Falta_Contexto'.\n"
        "- En caso de faltar contexto, debes llenar el campo 'missing_information' pidiendo "
        "educadamente lo mínimo necesario para radicar el trámite.\n\n"
        "Produce SIEMPRE la respuesta como JSON de salida estructurada de PqrsdValidationOutput."
    )

    prompt = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Analiza la siguiente PQRSD y extrae la estructura:\n\n{citizen_input}")
    ]

    try:
        # Pydantic structued output
        result_dict = await structured_llm.ainvoke(prompt)
        parsed: PqrsdValidationOutput = result_dict["parsed"]
        raw_message = result_dict["raw"]
        
        # Convert pydantic object to dict to return to API
        out = parsed.model_dump()
        out["usage"] = raw_message.usage_metadata if hasattr(raw_message, "usage_metadata") and raw_message.usage_metadata else {}
        return out
        
    except Exception as e:
        print(f"Error in PQRSD validation: {e}")
        # Retorno de fallback seguro ("falla por defecto") para no quebrar el backend de Laravel
        return {
            "is_valid": False,
            "status": "Incompleto_Falta_Contexto",
            "pqrsd_type": "Petición",
            "summary": "Error interno al validar con IA.",
            "suggested_department": "Ventanilla Única",
            "missing_information": "Su solicitud no pudo ser procesada automáticamente por falta de descripción.",
            "usage": {}
        }
