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
    """
    if current_usage is None:
        current_usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "thinking_tokens": 0
        }
    
    if not new_usage:
        return current_usage
    
    # Si new_usage es un objeto de LangChain (UsageMetadata)
    if hasattr(new_usage, "input_tokens"):
        current_usage["input_tokens"] += getattr(new_usage, "input_tokens", 0)
        current_usage["output_tokens"] += getattr(new_usage, "output_tokens", 0)
        current_usage["total_tokens"] += getattr(new_usage, "total_tokens", 0)
        
        # Manejo de thinking tokens si están en la metadata adicional
        extra = getattr(new_usage, "extra", {}) or {}
        thinking = extra.get("thinking_tokens", 0)
        current_usage["thinking_tokens"] += thinking
    elif isinstance(new_usage, dict):
        current_usage["input_tokens"] += new_usage.get("input_tokens", 0)
        current_usage["output_tokens"] += new_usage.get("output_tokens", 0)
        current_usage["total_tokens"] += new_usage.get("total_tokens", 0)
        current_usage["thinking_tokens"] += new_usage.get("thinking_tokens", 0)

    return current_usage
