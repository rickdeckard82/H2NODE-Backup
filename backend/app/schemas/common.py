from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, PlainSerializer

T = TypeVar("T")


def _as_utc_iso(dt: datetime | None) -> str | None:
    """Datas do banco são naive em UTC (containers rodam em UTC). Serializa com
    offset explícito para o front não interpretar como horário local."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


# Use nos campos de data que vêm do banco e são exibidos no painel.
UtcDatetime = Annotated[datetime, PlainSerializer(_as_utc_iso, return_type=str)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    detail: str
