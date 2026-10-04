"""Catálogo de la entidad que Laravel envía con cada documento (spec Recepción nueva §3). Sin dependencias pesadas: solo Pydantic."""
from typing import List, Optional

from pydantic import BaseModel, Field

# Campos del estado del grafo que no se devuelven a Laravel en el webhook.
INTERNAL_STATE_FIELDS = ("catalog",)


class CatalogDependency(BaseModel):
    id: int
    name: str


class CatalogTypology(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    series: Optional[str] = None
    subseries: Optional[str] = None
    dependence_ids: List[int] = Field(default_factory=list)


class FilingCatalog(BaseModel):
    filing_type: Optional[str] = None
    dependencies: List[CatalogDependency] = Field(default_factory=list)
    typologies: List[CatalogTypology] = Field(default_factory=list)


def without_internal_fields(state: dict) -> dict:
    """Copia del estado sin el catálogo: Laravel ya lo tiene y engordaría el webhook."""
    return {key: value for key, value in state.items() if key not in INTERNAL_STATE_FIELDS}
