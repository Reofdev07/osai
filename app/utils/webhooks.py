import httpx
from typing import Any, Dict, Optional

async def call_webhook(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 10
) -> bool:
    """
    Función genérica para llamar a un webhook externo async.
    
    - url: URL del webhook a llamar.
    - payload: datos JSON a enviar.
    - headers: headers HTTP opcionales.
    - timeout: timeout en segundos para la petición.

    Retorna True si la llamada fue exitosa, False si hubo error.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()  # Lanza error si status >= 400
            return True
        except httpx.HTTPError as e:
            print(f"Error al llamar webhook {url}: {e}")
            return False
