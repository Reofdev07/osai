import aiohttp
import asyncio
import hashlib
import hmac
import json
from typing import Dict, Any

from app.core.logger_config import logger


class WebhookNotifier:
    def __init__(self, webhook_url: str, secret: str):
        self.webhook_url = webhook_url
        self.secret = secret

    async def send_webhook(self, data: Dict[str, Any], max_retries: int = 3):
        """Enviar webhook con reintentos"""
        
        # Serializar el cuerpo de la solicitud para la firma
        request_body = json.dumps(data).encode('utf-8')
        
        # Generar la firma HMAC-SHA256
        signature = hmac.new(self.secret.encode('utf-8'), request_body, hashlib.sha256).hexdigest()
        
        headers = {
            'Content-Type': 'application/json',
            'X-Webhook-Signature': f'sha256={signature}'
        }
        
        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        self.webhook_url,
                        data=request_body, # Enviar el cuerpo serializado
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            logger.info(f"Webhook sent successfully: {data}")
                            return
                        else:
                            logger.warning(f"Webhook failed with status {response.status} - {await response.text()}")
                            
            except Exception as e:
                logger.error(f"Webhook attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Backoff exponencial
        
        logger.error(f"All webhook attempts failed for data: {data}")
