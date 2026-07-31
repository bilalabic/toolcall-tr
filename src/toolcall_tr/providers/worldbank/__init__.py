"""World Bank WDI sağlayıcıları."""

from toolcall_tr.providers.worldbank.indicators import TOOLS as HTTP_TOOLS
from toolcall_tr.providers.worldbank.indicators import adapter
from toolcall_tr.providers.worldbank.search import SEARCH_INDICATOR, build_adapter

TOOLS = (SEARCH_INDICATOR, *HTTP_TOOLS)

__all__ = ["SEARCH_INDICATOR", "TOOLS", "adapter", "build_adapter"]
