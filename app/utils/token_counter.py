import tiktoken

def count_tokens(text: str) -> int:
    """
        Counts the number of tokens in a given text. Used for token counting in the document analysis.
        Uses the cl100k_base tokenizer, which is compatible with models like gpt-3
    """
    # "cl100k_base" es el codificador usado por modelos como gpt-3.5-turbo y gpt-4
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(text))
    return num_tokens

def update_usage_metadata(current_usage: dict | None, new_usage: any) -> dict:
    """
    Updates and accumulates token usage metadata from LangChain.
    Ensures the dictionary is properly initialized to avoid KeyErrors.
    """
    # Inicialización robusta
    if current_usage is None or not isinstance(current_usage, dict):
        current_usage = {}
    
    # Asegurar que todas las llaves existan
    for key in ["input_tokens", "output_tokens", "total_tokens", "thinking_tokens"]:
        if key not in current_usage:
            current_usage[key] = 0
    
    if not new_usage:
        return current_usage
    
    # Si new_usage es un objeto de LangChain (UsageMetadata)
    if hasattr(new_usage, "input_tokens"):
        current_usage["input_tokens"] += getattr(new_usage, "input_tokens", 0)
        current_usage["output_tokens"] += getattr(new_usage, "output_tokens", 0)
        current_usage["total_tokens"] += getattr(new_usage, "total_tokens", 0)
        
        # Manejo de thinking tokens
        extra = getattr(new_usage, "extra", {}) or {}
        thinking = extra.get("thinking_tokens", 0)
        current_usage["thinking_tokens"] += thinking
        
    elif isinstance(new_usage, dict):
        current_usage["input_tokens"] += new_usage.get("input_tokens", 0)
        current_usage["output_tokens"] += new_usage.get("output_tokens", 0)
        current_usage["total_tokens"] += new_usage.get("total_tokens", 0)
        current_usage["thinking_tokens"] += new_usage.get("thinking_tokens", 0)

    return current_usage
