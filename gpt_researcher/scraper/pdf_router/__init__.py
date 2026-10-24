"""PDF page router: classify each page and parse it with the cheapest backend that can handle it."""

from .classify import classify
from .signals import compute_signals
from .types import PageSignals, Tier

__all__ = ["PageSignals", "Tier", "classify", "compute_signals"]
