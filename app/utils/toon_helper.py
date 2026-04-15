from typing import Dict, Any, Optional

def get_toon_context(state: Dict[str, Any]) -> str:
    """
    Genera una representación densa (TOON - Token-Oriented Object Notation)
    del contexto del documento para ahorrar tokens en los prompts.
    """
    # Usamos prefijos cortos para cada campo
    toon = []
    
    if state.get("subject"):
        toon.append(f"SBJ:{state['subject']}")
    
    if state.get("summary"):
        # Limitamos el resumen para no saturar nodos posteriores
        summ = (state["summary"][:200] + '..') if len(state["summary"]) > 200 else state["summary"]
        toon.append(f"SUM:{summ}")
        
    if state.get("intent_analysis"):
        intent = state["intent_analysis"].get("intencion", "N/A")
        toon.append(f"INT:{intent}")
        
    if state.get("classification"):
        tipology = state["classification"].get("tipologia_documental", "N/A")
        toon.append(f"TYP:{tipology}")

    # Si hay sentimientos o urgencias (para nodos legales/prioridad)
    if state.get("sentiment_analysis"):
        sent = state["sentiment_analysis"].get("sentimiento", {}).get("etiqueta", "N/A")
        urg = state["sentiment_analysis"].get("urgencia", {}).get("nivel", "N/A")
        toon.append(f"STMT:{sent}|URG:{urg}")

    return " | ".join(toon)
