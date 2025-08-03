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
