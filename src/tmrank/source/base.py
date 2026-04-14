from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from tmrank.domain import ParsedEvent, ParsedEventResults


class SourceProvider(ABC):
    source_name: str

    @abstractmethod
    def iter_tournaments(self) -> Iterable[ParsedEvent]:
        raise NotImplementedError

    @abstractmethod
    def fetch_event_results(self, source_event_id: str, page_id: int | None = None) -> ParsedEventResults:
        raise NotImplementedError
