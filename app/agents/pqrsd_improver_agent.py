from langchain_core.messages import HumanMessage, SystemMessage
from app.core.llm import create_llm

async def pqrsd_improver_agent(tipo_solicitud: str, subject: str, hechos: str, peticiones: str) -> dict:
    """
    Toma los campos crudos del ciudadano y los consolida en un solo documento
    formal, estructurado y listo para radicación legal.
    """
    llm = create_llm()
    
    system_prompt = (
        "Eres un experto jurídico y administrativo en Colombia (Leyes 1755 y 1437). "
        "Tu objetivo es tomar los datos fragmentados e informales que el ciudadano ingresó (Tipo, Asunto, Hechos, Peticiones) "
        "y redactar el cuerpo de un documento formal de PQRSD perfectamente estructurado.\n\n"
        "REGLAS:\n"
        "1. Mantén un tono respetuoso y formal propio de un documento público.\n"
        "2. Estructura el resultado usando obligatoriamente estos encabezados (en mayúsculas y negritas si es markdown):\n"
        "   - ASUNTO:\n"
        "   - HECHOS:\n"
        "   - PETICIÓN CONCRETA:\n"
        "3. NO inventes nombres, fechas ni lugares que el ciudadano no haya mencionado.\n"
        "4. NO uses saludos como 'Querida Alcaldía' ni firmas al final.\n"
        "5. Devuelve ÚNICAMENTE el texto consolidado."
    )
    
    raw_input = (
        f"TIPO: {tipo_solicitud}\n\n"
        f"ASUNTO: {subject}\n\n"
        f"HECHOS:\n{hechos}\n\n"
        f"LO QUE PIDE:\n{peticiones}"
    )
    
    prompt = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Redacta el cuerpo estructurado del PQRSD con la siguiente información:\n\n{raw_input}")
    ]
    
    try:
        response = await llm.ainvoke(prompt)
        usage = response.usage_metadata if hasattr(response, "usage_metadata") and response.usage_metadata else {}
        return {
            "improved_text": response.content.strip(),
            "usage": usage
        }
    except Exception as e:
        print(f"Error improving text: {e}")
        return {"improved_text": raw_input, "usage": {}}
