"""Türkçe Wikipedia metadata-only sağlayıcısı."""

from toolcall_tr.providers.wikimedia.metadata import (
    GET_PAGE_METADATA,
    LIST_PAGE_CATEGORIES,
    SEARCH_PAGES,
    TOOLS,
    adapter,
)

__all__ = ["GET_PAGE_METADATA", "LIST_PAGE_CATEGORIES", "SEARCH_PAGES", "TOOLS", "adapter"]
