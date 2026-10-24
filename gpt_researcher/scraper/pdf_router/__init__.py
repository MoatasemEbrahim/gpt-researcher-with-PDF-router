"""PDF page router: classify each page and parse it with the cheapest backend that can handle it."""

from .classify import classify
from .router import route_pdf
from .signals import compute_signals
from .types import PageOutcome, PageSignals, RouterResult, Tier

__all__ = ["PageOutcome", "PageSignals", "RouterResult", "Tier", "classify", "compute_signals", "route_pdf"]
