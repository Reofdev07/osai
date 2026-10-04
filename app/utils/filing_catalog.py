"""Catálogo de la entidad que Laravel envía con cada documento (spec Recepción nueva §3). Sin dependencias pesadas: solo Pydantic."""
from typing import List, Optional

from pydantic import BaseModel, Field

# Campos del estado del grafo que no se devuelven a Laravel en el webhook.
INTERNAL_STATE_FIELDS = ("catalog",)


class CatalogDependency(BaseModel):
    id: int
    name: str = Field(max_length=300)


class CatalogTypology(BaseModel):
    id: int
    name: str = Field(max_length=300)
    code: Optional[str] = Field(default=None, max_length=50)
    series: Optional[str] = Field(default=None, max_length=300)
    subseries: Optional[str] = Field(default=None, max_length=300)
    dependence_ids: List[int] = Field(default_factory=list, max_length=1000)


class FilingCatalog(BaseModel):
    filing_type: Optional[str] = Field(default=None, max_length=50)
    # Límites alineados con services.fastapi.catalog_max_typologies de Laravel.
    dependencies: List[CatalogDependency] = Field(default_factory=list, max_length=1000)
    typologies: List[CatalogTypology] = Field(default_factory=list, max_length=400)


def without_internal_fields(state: dict) -> dict:
    """Copia del estado sin el catálogo: Laravel ya lo tiene y engordaría el webhook."""
    return {key: value for key, value in state.items() if key not in INTERNAL_STATE_FIELDS}
