import uuid

from sqlmodel import Field

from .base import BaseModel


class FeatureCorrection(BaseModel, table=True):
    __tablename__ = "feature_corrections"
    __table_args__ = {"extend_existing": True}

    character_id: uuid.UUID = Field(foreign_key="characters.id", index=True)
    feature_name: str
    ai_value: str
    ai_confidence: float = Field(default=0)
    corrected_value: str
    photo_url: str
