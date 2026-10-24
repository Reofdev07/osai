"""Redacción de URLs prefirmadas y tokens antes de loguear o devolver errores (I-8)."""
import logging
import re

_URL_RE = re.compile(r"(https?://[^\s\"'<>?#]+)(?:[?#][^\s\"'<>]*)?", re.IGNORECASE)
_SECRET_PARAM_RE = re.compile(
    r"(?i)\b(X-Amz-[A-Za-z-]+|Signature|Token|access_token|api[_-]?key|Authorization)=([^&\s\"'<>]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+")


def redact_secrets(text) -> str:
    """Quita la query string de toda URL y enmascara tokens/firmas sueltos."""
    value = str(text)
    value = _URL_RE.sub(lambda m: m.group(1) + ("?[REDACTADO]" if m.group(0) != m.group(1) else ""), value)
    value = _SECRET_PARAM_RE.sub(r"\1=[REDACTADO]", value)
    return _BEARER_RE.sub(r"\1 [REDACTADO]", value)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_secrets(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def install_log_redaction() -> None:
    """Filtro en los loggers de librerías que escriben la URL de la petición (httpx registra GET <url prefirmada>)."""
    for name in ("httpx", "httpcore", "httpx._client"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _RedactFilter) for f in lg.filters):
            lg.addFilter(_RedactFilter())
