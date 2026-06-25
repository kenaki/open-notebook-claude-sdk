from typing import Optional, Type, TypeVar

from fastapi import HTTPException

from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import NotFoundError

T = TypeVar("T", bound=ObjectModel)


def ensure_prefix(id: str, table: str) -> str:
    prefix = f"{table}:"
    return id if id.startswith(prefix) else f"{prefix}{id}"


async def get_or_404(
    model_cls: Type[T],
    id: str,
    name: str,
    *,
    prefix: Optional[str] = None,
) -> T:
    if prefix:
        id = ensure_prefix(id, prefix)
    try:
        return await model_cls.get(id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"{name} not found")
