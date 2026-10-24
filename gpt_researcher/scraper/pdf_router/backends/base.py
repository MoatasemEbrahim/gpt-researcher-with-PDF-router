"""The interface every page backend implements."""

from typing import Protocol

from ..types import Tier

# Written where a figure was: its label text is dropped, its caption kept.
FIGURE_MARKER = "<!-- figure -->"


class PageBackend(Protocol):
    name: str
    tier: Tier

    def available(self) -> bool:
        """Whether this backend can run here (optional packages installed)."""
        ...

    def parse(self, pdf: bytes, pages: list[int]) -> dict[int, str]:
        """Markdown for each requested page (0-based page number -> Markdown).

        Takes only picklable arguments, so it can run in another process, and
        opens its own copy of the document.
        """
        ...
