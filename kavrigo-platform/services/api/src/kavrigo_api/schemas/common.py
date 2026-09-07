"""Shared response shapes."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Page", "PageParams"]


class PageParams(BaseModel):
    """Cursor pagination parameters.

    Cursor rather than offset: over append-heavy data an offset page returns duplicates and
    silently skips rows when the underlying set changes between requests.
    """

    model_config = ConfigDict(extra="forbid")

    cursor: Annotated[str | None, Field(default=None, max_length=512)] = None
    limit: Annotated[int, Field(default=50, ge=1, le=200)] = 50


class Page[T](BaseModel):
    """One page of results."""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
