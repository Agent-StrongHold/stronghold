from sqlmodel import Field

from .base import BaseModel


class Customer(BaseModel, table=True):
    __tablename__ = "customers"
    __table_args__ = {"extend_existing": True}

    email: str = Field(unique=True, index=True)
    name: str
    phone: str = ""
    source: str = ""
    source_id: str = ""
    email_consent: bool = Field(default=False)
