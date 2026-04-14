from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmrank.db.models import Event, EventCompetitor, EventResult, TeamMembership


class InspectService:
    def __init__(self, session: Session):
        self.session = session

    def inspect_event(self, source_event_id: str) -> dict:
        event = self.session.scalar(select(Event).where(Event.source_event_id == source_event_id))
        if not event:
            raise LookupError(f"Event '{source_event_id}' was not found.")
        results = list(
            self.session.execute(
                select(EventResult, EventCompetitor)
                .join(EventCompetitor, EventResult.competitor_id == EventCompetitor.id)
                .where(EventResult.event_id == event.id)
                .order_by(EventResult.placement_low.asc(), EventCompetitor.display_name.asc())
            )
        )
        payload = {
            "event": {
                "source_event_id": event.source_event_id,
                "name": event.name,
                "series": event.series,
                "tier": event.tier,
                "mode": event.mode,
                "type": event.event_type,
                "start_date": event.start_date,
                "end_date": event.end_date,
                "page_id": event.page_id,
                "page_name": event.page_name,
            },
            "results": [],
        }
        for result, competitor in results:
            item = {
                "placement": result.placement_text,
                "competitor_type": competitor.competitor_type,
                "display_name": competitor.display_name,
                "canonical_slug": competitor.canonical_slug,
                "prize": float(result.prize) if result.prize is not None else None,
                "points": float(result.points) if result.points is not None else None,
                "members": [],
            }
            if competitor.competitor_type == "team":
                memberships = list(
                    self.session.scalars(
                        select(TeamMembership).where(TeamMembership.team_competitor_id == competitor.id)
                    )
                )
                for membership in memberships:
                    member = self.session.get(EventCompetitor, membership.player_competitor_id)
                    if member:
                        item["members"].append(member.display_name)
            payload["results"].append(item)
        return payload
