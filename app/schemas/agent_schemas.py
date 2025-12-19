from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class ExtractionSummary(BaseModel):
    resumen: str = Field(description="Resumen del documento en 3-4 oraciones en español.")
    asunto: str = Field(description="Asunto o título corto descriptivo del documento.")
    fecha: Optional[str] = Field(description="Fecha del documento (si está disponible) en formato YYYY-MM-DD.")

class IntentAnalysis(BaseModel):
    intencion: str = Field(description="La intención principal del documento (Solicitar Información, Queja, Pago, etc.)")
    justificacion: str = Field(description="Una frase corta que explique por qué elegiste esa intención.")

class SentimentUrgency(BaseModel):
    etiqueta: str = Field(description="Positivo | Neutro | Negativo")
    puntuacion: float = Field(description="Número de -1.0 a 1.0")
    justificacion: str = Field(description="Breve explicación del sentimiento.")
    urgencia_nivel: str = Field(description="Baja | Media | Alta | Crítica")
    urgencia_justificacion: str = Field(description="Explica por qué el lenguaje implica este nivel de urgencia.")

class ClassificationOutput(BaseModel):
    tipologia_documental: str = Field(description="Nombre exacto de la tipología documental.")
    confianza: float = Field(description="Nivel de confianza entre 0.0 y 1.0.")

class Entity(BaseModel):
    nombre: str = Field(description="Nombre de la entidad o persona.")
    rol: str = Field(description="Rol o relación con el documento.")

class DateEntity(BaseModel):
    fecha: str = Field(description="Fecha encontrada (YYYY-MM-DD o texto).")
    descripcion: str = Field(description="Contexto de la fecha.")

class AmountEntity(BaseModel):
    valor: str = Field(description="Monto monetario.")
    descripcion: str = Field(description="Concepto del monto.")

class CodeEntity(BaseModel):
    codigo: str = Field(description="El código o número de referencia.")
    descripcion: str = Field(description="Contexto del código.")

class GenericData(BaseModel):
    dato: str = Field(description="Nombre del dato.")
    descripcion: str = Field(description="Valor o descripción.")

class TimelineEvent(BaseModel):
    fecha: str = Field(description="Fecha del evento.")
    evento: str = Field(description="Descripción del suceso.")

class EntitiesOutput(BaseModel):
    personas_naturales: List[Entity] = Field(default_factory=list)
    personas_juridicas: List[Entity] = Field(default_factory=list)
    fechas: List[DateEntity] = Field(default_factory=list)
    montos: List[AmountEntity] = Field(default_factory=list)
    codigos: List[CodeEntity] = Field(default_factory=list)
    otros: List[GenericData] = Field(default_factory=list)
    linea_de_tiempo: List[TimelineEvent] = Field(default_factory=list)
    hechos_relevantes: List[str] = Field(default_factory=list)

class PriorityOutput(BaseModel):
    prioridad: str = Field(description="Crítica | Alta | Media | Baja")
    justificacion_legal: str = Field(description="Sustento con referencia expresa a la ley.")
    termino_respuesta_sugerido_dias: int

class ComplianceOutput(BaseModel):
    cumple_normativa: bool
    resumen_ejecutivo: str = Field(description="Resumen conciso del cumplimiento (2-3 oraciones).")
    analisis_detallado: str = Field(description="Verificación detallada por puntos y recomendaciones archivísticas.")

class MasterEnrichmentOutput(BaseModel):
    intencion: IntentAnalysis
    sentimiento_urgencia: SentimentUrgency
    clasificacion: ClassificationOutput
    etiquetas: List[str] = Field(description="Lista de 5-7 etiquetas descriptivas en español.")

class TagsOutput(BaseModel):
    tags: List[str] = Field(description="Lista de 5-7 etiquetas descriptivas en español.")
