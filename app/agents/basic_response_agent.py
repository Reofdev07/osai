import json
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

        usage = None
        async for chunk in llm.astream(prompt):
            if chunk.usage_metadata:
                usage = chunk.usage_metadata
            if chunk.content:
                yield json.dumps({"type": "content", "content": chunk.content}, ensure_ascii=False) + "\n"
        
        # Formato NDJSON para metadata
        if usage:
            usage_data = {
                "input_tokens": usage.get("input_tokens", 0) if isinstance(usage, dict) else getattr(usage, "input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0) if isinstance(usage, dict) else getattr(usage, "output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0) if isinstance(usage, dict) else getattr(usage, "total_tokens", 0)
            }
            yield json.dumps({"type": "usage", "data": usage_data}, ensure_ascii=False) + "\n"

    except Exception as e:
        yield json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False) + "\n"

    