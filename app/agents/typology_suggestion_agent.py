import json
import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.llm import create_llm
from app.core.config import settings

llm = create_llm()


def get_all_typologies():
    """
    Obtiene todas las tipologías configuradas en SDG-Back-api.
    Hace una llamada HTTP al backend para obtener las tipologías.
    """
    try:
        backend_url = settings.BACKEND_URL.rstrip('/')
        response = httpx.get(
            f"{backend_url}/api/v1/admin/document-typologies",
            timeout=15
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('data', []) or []
        return []
    except Exception as e:
        print(f"Error fetching typologies from backend: {e}")
        return []


async def suggest_typology_agent(context_payload: dict):
    """
    Agente que sugiere la tipología documental basada en el contenido del documento.
    Recibe el contenido analizado y sugiere la tipología más apropiada de la TRD.
    """
    try:
        document_content = context_payload.get('document_content', '')
        document_summary = context_payload.get('summary', '')
        subject = context_payload.get('subject', '')

        typologies = get_all_typologies()
        typology_list = "\n".join([
            f"- {t['name']} ({t.get('code', 'N/A')}): {t.get('response_days', '?')} días {t.get('day_type', 'business')}"
            for t in typologies
        ]) if typologies else "No hay tipologías configuradas."

        system_prompt = (
            "Role: Document Classification Assistant (TRD). "
            "You are an expert in Colombian documentary classification (TRD - Tabla de Retención Documental). "
            "Based on the document content, subject, and summary, suggest the most appropriate document typology. "
            "Consider the response days and legal basis of each typology. "
            "Output: JSON with 'typology_id', 'confidence', and 'reasoning'. "
            "If no typology fits well, return null values."
        )

        user_prompt = f"""
Document Subject: {subject}
Document Summary: {document_summary}
Document Content Preview: {document_content[:1000] if document_content else 'N/A'}

Available Typologies (TRD):
{typology_list}

Task: Suggest the most appropriate typology_id for this document.
Consider: response deadlines, document type, and Colombian legal regulations (Ley 1755 de 2015, etc.)

Output format:
{{
    "typology_id": <id from the list or null>,
    "typology_name": "<name>" or null,
    "confidence": <0-100>,
    "reasoning": "<brief explanation>"
}}
        """

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

        if usage:
            usage_data = {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }
            yield json.dumps({"type": "usage", "data": usage_data}, ensure_ascii=False) + "\n"

    except Exception as e:
        yield json.dumps({"type": "error", "content": str(e)}, ensure_ascii=False) + "\n"