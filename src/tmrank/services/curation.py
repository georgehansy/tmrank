from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from tmrank.config_models import MajorEventRule, TournamentRule, TournamentRuleMatch, TournamentRulesConfig
from tmrank.domain import CuratedEvent
from tmrank.utils import parse_date


@dataclass(slots=True)
class EventView:
    source_event_id: str
    page_id: int | None
    tier: int | None
    page_name: str | None
    name: str
    series: str | None
    mode: str | None
    event_type: str | None
    start_date: date | None
    end_date: date | None


class TournamentCurator:
    def __init__(self, config: TournamentRulesConfig):
        self.config = config

    def evaluate(self, event: EventView) -> CuratedEvent:
        include = self.config.defaults.include
        weight = self.config.defaults.weight
        tags = list(self.config.defaults.tags)
        for rule in self.config.rules:
            if self._matches(rule, event):
                if rule.include is not None:
                    include = rule.include
                if rule.weight is not None:
                    weight = rule.weight
                if rule.tags is not None:
                    tags = list(rule.tags)
        return CuratedEvent(
            source_event_id=event.source_event_id,
            page_id=event.page_id,
            name=event.name,
            series=event.series,
            mode=event.mode,
            event_type=event.event_type,
            start_date=event.start_date,
            end_date=event.end_date,
            include=include,
            weight=weight,
            tags=tags,
        )

    def _matches(self, rule: TournamentRule, event: EventView) -> bool:
        return event_matches_rule(rule.match, event)


class MajorEventSelector:
    def __init__(self, rules: list[MajorEventRule]):
        self.rules = rules

    def is_major(self, event: EventView) -> bool:
        return bool(self.matched_rule_names(event))

    def matched_rule_names(self, event: EventView) -> list[str]:
        return [rule.name for rule in self.rules if event_matches_rule(rule.match, event)]


def event_matches_rule(match: TournamentRuleMatch, event: EventView) -> bool:
    if match.source_event_id and match.source_event_id != event.source_event_id:
        return False
    if match.pageid is not None and match.pageid != event.page_id:
        return False
    if match.tier is not None and match.tier != event.tier:
        return False
    if match.page_name and match.page_name != (event.page_name or ""):
        return False
    if match.page_name_regex and not re.search(match.page_name_regex, event.page_name or ""):
        return False
    if match.name and match.name != event.name:
        return False
    if match.name_regex and not re.search(match.name_regex, event.name):
        return False
    if match.series and match.series != (event.series or ""):
        return False
    if match.mode and match.mode != (event.mode or ""):
        return False
    if match.type and match.type != (event.event_type or ""):
        return False
    if match.start_date_gte:
        start_gte = parse_date(match.start_date_gte)
        if start_gte and event.start_date and event.start_date < start_gte:
            return False
    if match.start_date_lte:
        start_lte = parse_date(match.start_date_lte)
        if start_lte and event.start_date and event.start_date > start_lte:
            return False
    return True
