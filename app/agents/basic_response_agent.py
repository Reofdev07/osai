from langchain_core.messages import HumanMessage, SystemMessage
from app.core.llm import create_llm




# Create instance of LLM
llm = create_llm()


async def basic_response_agent(context_payload: dict):
    """
    Agente de respuesta básica optimizado con TOON.
    """
    from app.utils.toon_helper import get_toon_context
    
    try:
        # Generar contexto TOON denso
        ctx = get_toon_context(context_payload)
        task_desc = context_payload.get('task_description', 'N/A')

        system_prompt = (
            "Role: Doc Mgmt Assistant. Output: Single formal closure note (1-2 sentences). "
            "Rule: Passive voice/3rd person. No greetings. Contextual."
        )

        user_prompt = f"Ctx: {ctx}\nTask: {task_desc}\nInstruction: Write closure note."

        prompt = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        async for chunk in llm.astream(prompt):
            yield chunk.content

    except Exception as e:
        yield f"[ERROR: {str(e)}]"
    