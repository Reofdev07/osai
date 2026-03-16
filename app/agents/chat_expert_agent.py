import json
from app.core.llm import create_llm
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, trim_messages

llm = create_llm()

async def expert_chat_stream_generator(full_payload: dict):
    """
    Generador asíncrono para el chat experto.
    Construye un System Prompt con el contexto del expediente y transmite
    la respuesta del LLM chunk a chunk.
    """

    # 1. Extraemos el contexto real que nos envía el frontend
    context = full_payload.get('context', {})
    if not isinstance(context, dict):
        context = {}
    
    # Helper para obtener datos de un dict de forma segura
    def get_safe(d, key, default=None):
        if isinstance(d, dict):
            return d.get(key, default)
        return default

    # Extraemos las secciones del contexto con seguridad
    info = get_safe(context, 'general_info', {})
    analysis = get_safe(context, 'ai_analysis', {})
    parties = get_safe(context, 'parties', {})
    history = get_safe(context, 'history', [])
    task = get_safe(context, 'current_task', {})

    # Aseguramos tipos correctos para evitar AttributeErrors
    if not isinstance(info, dict): info = {}
    if not isinstance(analysis, dict): analysis = {}
    if not isinstance(parties, dict): parties = {}
    if not isinstance(task, dict): task = {}
    if not isinstance(history, list): history = []

    # Pre-formateamos los datos para el prompt de forma segura
    radicado = get_safe(info, 'radicado_number', 'N/A')
    asunto = get_safe(info, 'subject', 'No especificado')
    remitente = get_safe(info, 'sender', 'No identificado')
    fecha_limite = get_safe(info, 'response_deadline_at', 'Sin fecha límite')
    estado = get_safe(info, 'current_status', 'No definido')
    dependencia = get_safe(info, 'dependency', 'No asignada')
    usuario_actual = get_safe(info, 'responsible_user', 'un funcionario')
    
    resumen = get_safe(analysis, 'summary') or "Información no disponible (el documento aún no ha sido resumido)."
    
    intent_data = get_safe(analysis, 'intent', {})
    intencion = get_safe(intent_data, 'intencion', 'Indeterminada o no detectada')
    
    parties_claimant = get_safe(parties, 'claimant', 'No identificado')
    parties_defendant = get_safe(parties, 'defendant', 'No identificado')
    
    entities_data = get_safe(analysis, 'entities', {})
    hechos = get_safe(entities_data, 'hechos_relevantes', [])
    if isinstance(hechos, list) and hechos:
        hechos_str = ", ".join(hechos)
    else:
        hechos_str = "No se han extraído hechos relevantes del documento aún."

    # Formateamos el historial para que sea legible y seguro
    history_lines = []
    for h in history:
        if isinstance(h, dict):
            date = get_safe(h, 'date', 'N/A')
            desc = get_safe(h, 'description', 'Sin descripción')
            user = get_safe(h, 'user', 'Sistema')
            history_lines.append(f"- {date}: {desc} (Por: {user})")
    
    history_str = "\n".join(history_lines) if history_lines else "No hay historial de eventos registrados."

    tarea_nombre = get_safe(task, 'name', 'Revisión general')

    # Construimos un System Prompt de nivel experto
    system_prompt = f"""
        Eres un asistente experto en gestión de expedientes jurídicos y administrativos. 
        Tu rol es ayudar al usuario a completar con éxito la tarea asignada dentro del caso #{radicado}.

        === PERFIL DEL USUARIO ===
        - Usuario actual: {usuario_actual}
        - Tarea pendiente: "{tarea_nombre}"

        === CONTEXTO COMPLETO DEL EXPEDIENTE ===

        **1. Información General**
        - Asunto: {asunto}
        - Remitente (Ciudadano/Entidad): {remitente}
        - Fecha límite de respuesta: {fecha_limite}
        - Estado actual del caso: {estado}
        - Dependencia responsable: {dependencia}

        **2. Análisis Automático del Documento Principal**
        - Resumen: {resumen}
        - Intención detectada: {intencion}
        - Partes involucradas:
            - Solicitante: {parties_claimant}
            - Demandado: {parties_defendant}
        - Hechos relevantes: {hechos_str}

        **3. Historial reciente del caso (últimos eventos)**
        {history_str}

        === FIN DEL CONTEXTO ===

        === INSTRUCCIONES DE RESPUESTA ===

        1. **Estilo de comunicación**
        - Usa un tono claro, profesional, pero cercano.
        - Evita tecnicismos innecesarios, a menos que el usuario lo requiera.
        - Responde en **español neutro**.
        - Sé conciso, pero incluye todos los detalles relevantes.

        2. **Reglas de comportamiento**
        - Si el usuario saluda o conversa: responde de forma natural en texto plano.
        - Si el usuario pide ayuda con la tarea: ofrece **pasos concretos**, **recomendaciones prácticas** y, si corresponde, ejemplos redactados.
        - Si el usuario pide interpretación del documento: explica de manera resumida y accesible.
        - Si el usuario pide una acción (ej. redactar respuesta, resumir, generar formato): entrega un borrador **listo para usar**, bien estructurado y formal.
        - IMPORTANTE: Si un campo del "Análisis Automático" indica que la información no está disponible o no ha sido extraída, informa al usuario con honestidad si te pregunta por ello, sugiriendo que el documento podría no haber sido procesado completamente. No inventes datos.

        3. **Prioridad**
        - Tu meta principal es ayudar al usuario a **completar la tarea pendiente** de la forma más rápida y precisa posible.
        - No inventes información que no esté en el contexto, pero sí puedes inferir **con lógica y claridad** basada en lo que sí conoces.

        """
    
    # 1. Construir la lista completa de mensajes
    raw_messages = [SystemMessage(content=system_prompt)]
    for msg in full_payload.get('messages', []):
        content = msg.get('content') or ""
        if msg['role'] == 'user':
            raw_messages.append(HumanMessage(content=content))
        elif msg['role'] == 'assistant':
            raw_messages.append(AIMessage(content=content))

    # 2. Aplicar trim_messages (Estrategia oficial de LangChain)
    # Usamos max_tokens=7 (System + 6 mensajes) con token_counter=len para simular conteo de mensajes
    # Aseguramos que siempre empiece con un mensaje del Humano para la coherencia del modelo.
    messages_for_llm = trim_messages(
        raw_messages,
        strategy="last",
        token_counter=len,
        max_tokens=7,
        start_on="human",
        include_system=True,
    )
            
    # Llamamos al LLM con el contexto optimizado (System Prompt + Historial Recortado)
    response_stream = llm.astream(messages_for_llm)

    final_usage = None
    async for chunk in response_stream:
        # Capturamos la metadata de uso
        if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
            final_usage = chunk.usage_metadata
            
        if chunk.content:
            yield json.dumps({"type": "content", "content": chunk.content}, ensure_ascii=False) + "\n"

    # Enviamos la metadata como un objeto estructurado al final
    if final_usage:
        usage_dict = {
            "input_tokens": final_usage.get("input_tokens", 0) if isinstance(final_usage, dict) else getattr(final_usage, "input_tokens", 0),
            "output_tokens": final_usage.get("output_tokens", 0) if isinstance(final_usage, dict) else getattr(final_usage, "output_tokens", 0),
            "total_tokens": final_usage.get("total_tokens", 0) if isinstance(final_usage, dict) else getattr(final_usage, "total_tokens", 0)
        }
        yield json.dumps({"type": "usage", "data": usage_dict}, ensure_ascii=False) + "\n"
