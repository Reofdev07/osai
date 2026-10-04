"""Catálogo de la entidad que Laravel envía con cada documento (spec Recepción nueva §3). Sin dependencias pesadas: solo Pydantic."""
from typing import List, Optional

from pydantic import BaseModel, Field

# Campos del estado del grafo que no se devuelven a Laravel en el webhook.
INTERNAL_STATE_FIELDS = ("catalog",)


class CatalogDependency(BaseModel):
    id: int
    name: str = Field(max_length=255)


class CatalogTypology(BaseModel):
    id: int
    name: str = Field(max_length=255)
    code: Optional[str] = Field(default=None, max_length=255)
    series: Optional[str] = Field(default=None, max_length=255)
    subseries: Optional[str] = Field(default=None, max_length=255)
    dependence_ids: List[int] = Field(default_factory=list, max_length=1000)


class FilingCatalog(BaseModel):
    filing_type: Optional[str] = Field(default=None, max_length=255)
    # Límites alineados con services.fastapi.catalog_max_typologies de Laravel.
    dependencies: List[CatalogDependency] = Field(default_factory=list, max_length=1000)
    typologies: List[CatalogTypology] = Field(default_factory=list, max_length=400)


def without_internal_fields(state: dict) -> dict:
    """Copia del estado sin el catálogo: Laravel ya lo tiene y engordaría el webhook."""
    return {key: value for key, value in state.items() if key not in INTERNAL_STATE_FIELDS}


SENDER_FIELDS = ("name", "kind", "identification", "phone", "address", "email")
SENDER_KINDS = ("natural", "juridica", "entidad")
TRD_LEVELS = ("publico", "clasificado", "reservado", "confidencial")
LEGACY_LEVELS = {"public": "publico", "internal": "clasificado", "confidential": "confidencial", "restricted": "reservado"}
MAX_TEXT = 255

ROLE_BY_FILING_TYPE = {
    "ENT": "la dependencia de la sede que debe recibir y tramitar el documento",
    "PQR": "la dependencia de la sede que debe recibir y tramitar el documento",
    "INT": "la dependencia de la sede que recibe el documento",
    "IMA": "la dependencia de la sede que recibe el documento",
    "SAL": "la dependencia de la sede que produce y firma el documento",
}


def catalog_prompt_block(catalog: Optional[dict]) -> str:
    """Lista de ids que la IA puede usar. Va fuera de <documento>: son datos de configuración, no del documento."""
    if not catalog or not (catalog.get("dependencies") or catalog.get("typologies")):
        return ""
    role = ROLE_BY_FILING_TYPE.get(str(catalog.get("filing_type") or "").upper(), "la dependencia de la sede que debe gestionar el documento")
    lines = [
        "CATÁLOGO DE LA ENTIDAD (use SOLO estos ids; si ninguno corresponde, deje el id en null y la confianza en 0):",
        f"Dependencias (dependence_id = {role}):",
    ]
    lines += [f"- [{dep['id']}] {dep['name']}" for dep in catalog.get("dependencies") or []]
    lines.append("Tipologías documentales (typology_id):")
    for typ in catalog.get("typologies") or []:
        code = f" (código {typ['code']})" if typ.get("code") else ""
        trd = " › ".join(part for part in (typ.get("series"), typ.get("subseries")) if part)
        deps = ", ".join(str(dep) for dep in typ.get("dependence_ids") or [])
        lines.append(f"- [{typ['id']}] {typ['name']}{code}" + (f" — {trd}" if trd else "") + (f" — dependencias: {deps}" if deps else ""))
    return "\n".join(lines)


def _as_id(value) -> Optional[int]:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, number)), 2)


def _text(value) -> Optional[str]:
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:MAX_TEXT] if text else None


def empty_suggestion() -> dict:
    return {
        "typology_id": None, "typology_confidence": 0.0, "dependence_id": None, "dependence_confidence": 0.0,
        "sender": {field: None for field in SENDER_FIELDS}, "sender_confidence": 0.0,
    }


def validate_suggestion(raw: Optional[dict], catalog: Optional[dict]) -> dict:
    """Solo ids del catálogo (un id ajeno se descarta con confianza 0); la dependencia debe ser la dueña de la tipología."""
    raw = raw or {}
    suggestion = empty_suggestion()
    typologies = {typ["id"]: typ for typ in (catalog or {}).get("typologies") or []}
    dependence_ids = {dep["id"] for dep in (catalog or {}).get("dependencies") or []}

    typology_id = _as_id(raw.get("typology_id"))
    if typology_id in typologies:
        suggestion["typology_id"], suggestion["typology_confidence"] = typology_id, _confidence(raw.get("typology_confidence"))
    dependence_id = _as_id(raw.get("dependence_id"))
    if dependence_id in dependence_ids:
        suggestion["dependence_id"], suggestion["dependence_confidence"] = dependence_id, _confidence(raw.get("dependence_confidence"))

    if suggestion["typology_id"] is not None:
        owners = [dep for dep in typologies[suggestion["typology_id"]].get("dependence_ids") or [] if dep in dependence_ids]
        if owners and suggestion["dependence_id"] not in owners:
            if len(owners) == 1:
                suggestion["dependence_id"], suggestion["dependence_confidence"] = owners[0], suggestion["typology_confidence"]
            else:
                suggestion["dependence_id"], suggestion["dependence_confidence"] = None, 0.0

    sender = raw.get("sender") or {}
    suggestion["sender"] = {field: _text(sender.get(field)) for field in SENDER_FIELDS}
    kind = (suggestion["sender"]["kind"] or "").lower()
    suggestion["sender"]["kind"] = kind if kind in SENDER_KINDS else None
    if suggestion["sender"]["name"]:
        suggestion["sender_confidence"] = _confidence(raw.get("sender_confidence"))
    return suggestion


def normalize_sensitivity_level(level) -> str:
    """Nivel de acceso en el vocabulario de la TRD; ante un valor desconocido no se presume «público» (Ley 1581)."""
    value = str(level or "").strip().lower()
    if value in TRD_LEVELS or value == "no_evaluado":
        return value
    return LEGACY_LEVELS.get(value, "clasificado")
