import json
from app.core.llm import create_llm
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, trim_messages
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

llm = create_llm()

async def expert_chat_stream_generator(full_payload: dict):
    """
    Generador asíncrono para el chat experto usando Tool Calling (Herramientas).
    Esto optimiza el uso de tokens y mejora la precisión al permitir que el 
    agente consulte solo la información que necesita.
    """

    # 1. Extraemos el contexto que nos envía el frontend
    context = full_payload.get('context', {})
    if not isinstance(context, dict):
        context = {}
    
    def get_safe(d, key, default=None):
        if isinstance(d, dict):
            return d.get(key, default)
        return default

    info = get_safe(context, 'general_info', {})
    analysis = get_safe(context, 'ai_analysis', {})
    parties = get_safe(context, 'parties', {})
    history = get_safe(context, 'history', [])
    task = get_safe(context, 'current_task', {})

    radicado = get_safe(info, 'radicado_number', 'N/A')
    tarea_nombre = get_safe(task, 'name', 'Revisión general')

    # --- DEFINICIÓN DE HERRAMIENTAS (DINÁMICAS SEGÚN EL CONTEXTO) ---
    
    @tool
    def get_document_summary():
        """Obtiene el resumen detallado, la intención detectada y los hechos relevantes del documento principal."""
        resumen = get_safe(analysis, 'summary') or "No disponible."
        intent_data = get_safe(analysis, 'intent', {})
        intencion = get_safe(intent_data, 'intencion', 'No detectada')
        
        entities_data = get_safe(analysis, 'entities', {})
        hechos = get_safe(entities_data, 'hechos_relevantes', [])
        hechos_str = ", ".join(hechos) if hechos else "No extraídos."
        
        return {
            "resumen_ia": resumen,
            "intencion": intencion,
            "hechos": hechos_str
        }

    @tool
    def get_case_metadata():
        """Consulta información general: remitente, asunto, fechas límite, dependencia y estado del caso."""
        return {
            "radicado": radicado,
            "asunto": get_safe(info, 'subject', 'N/A'),
            "remitente": get_safe(info, 'sender', 'N/A'),
            "fecha_vencimiento": get_safe(info, 'response_deadline_at', 'N/A'),
            "estado_peticion": get_safe(info, 'current_status', 'N/A'),
            "dependencia": get_safe(info, 'dependency', 'N/A'),
            "responsable": get_safe(info, 'responsible_user', 'N/A')
        }

    @tool
    def get_event_timeline():
        """Obtiene el historial de trazas y eventos recientes registrados en este expediente."""
        history_lines = []
        for h in (history or []):
            if isinstance(h, dict):
                date = get_safe(h, 'date', 'N/A')
                desc = get_safe(h, 'description', 'N/A')
                user = get_safe(h, 'user', 'Sistema')
                history_lines.append(f"- {date}: {desc} (Por: {user})")
        return "\n".join(history_lines) if history_lines else "Sin eventos previos."

    @tool
    def get_parties_involved():
        """Consulta quienes son las partes involucradas (Solicitante y Demandado)."""
        return {
            "solicitante": get_safe(parties, 'claimant', 'No identificado'),
            "demandado": get_safe(parties, 'defendant', 'No identificado')
        }

    tools = [get_document_summary, get_case_metadata, get_event_timeline, get_parties_involved]

    # --- CONFIGURACIÓN DEL AGENTE ---

    system_prompt = f"""
        Eres un asistente experto jurídico-administrativo de OSAI.
        Tu misión es ayudar al usuario con el expediente #{radicado}.
        
        INSTRUCCIONES:
        1. **Usa tus herramientas**: No asumas datos. Si te preguntan algo específico, usa la herramienta adecuada.
        2. **Tarea pendiente**: El usuario debe completar "{tarea_nombre}". Oriéntalo basándote en los hechos del caso.
        3. **Estilo**: Profesional, cortés y eficiente. Responde en español.
        4. **Limitación**: Si la herramienta no devuelve información, indica que el dato no está disponible en este momento.
    """

    # Preparamos mensajes iniciales
    raw_messages = []
    for msg in full_payload.get('messages', []):
        content = msg.get('content') or ""
        if msg['role'] == 'user':
            raw_messages.append(HumanMessage(content=content))
        elif msg['role'] == 'assistant':
            raw_messages.append(AIMessage(content=content))

    # Optimización de ventana de chat
    messages_for_llm = trim_messages(
        raw_messages,
        strategy="last",
        token_counter=len,
        max_tokens=6,
        start_on="human",
        include_system=False, # El sistema se añade en el react_agent
    )

    # Creamos el agente de razonamiento
    agent = create_react_agent(llm, tools=tools, state_modifier=system_prompt)

    # Ejecutamos el agente en modo stream
    async for chunk in agent.astream({"messages": messages_for_llm}, stream_mode="messages"):
        msg, metadata = chunk
        
        # Solo emitimos el contenido si es un mensaje de la IA (no una llamada a herramienta interna)
        if isinstance(msg, AIMessage) and msg.content:
            # Si el mensaje tiene tool_calls, no lo emitimos al usuario (es pensamiento interno)
            if not msg.tool_calls:
                yield json.dumps({"type": "content", "content": msg.content}, ensure_ascii=False) + "\n"
        
        # Capturamos el uso de tokens al final del proceso
        if metadata.get("langgraph_node") == "agent":
            if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                usage = msg.usage_metadata
                usage_dict = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0)
                }
                # Solo emitimos el último usage que encontremos
                self_usage = usage_dict

    # Envío final de usage (aproximado basado en el último nodo del agente)
    # Nota: LangGraph a veces emite varios usage, aquí capturamos el último disponible
    # Para simplicidad en este MVP, si self_usage no se capturó, enviamos ceros.
    try:
        if 'self_usage' in locals():
            yield json.dumps({"type": "usage", "data": self_usage}, ensure_ascii=False) + "\n"
    except:
        pass
