from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tmrank.db.models import EntityAlias, EventCompetitor, Player, Team


class AliasQaService:
    def __init__(self, session: Session):
        self.session = session

    def get_status(self, *, limit: int = 20, include_orphans: bool = False) -> dict[str, Any]:
        return {
            "players": self._entity_status("player", Player, limit=limit, include_orphans=include_orphans),
            "teams": self._entity_status("team", Team, limit=limit, include_orphans=include_orphans),
        }

    def cleanup_orphans(self, *, dry_run: bool = True) -> dict[str, int]:
        orphan_player_ids = [
            row[0]
            for row in self.session.execute(
                select(Player.id)
                .outerjoin(EventCompetitor, EventCompetitor.player_id == Player.id)
                .group_by(Player.id)
                .having(func.count(EventCompetitor.id) == 0)
            )
        ]
        orphan_team_ids = [
            row[0]
            for row in self.session.execute(
                select(Team.id)
                .outerjoin(EventCompetitor, EventCompetitor.team_id == Team.id)
                .group_by(Team.id)
                .having(func.count(EventCompetitor.id) == 0)
            )
        ]
        orphan_player_slugs = [
            row[0] for row in self.session.execute(select(Player.canonical_slug).where(Player.id.in_(orphan_player_ids)))
        ] if orphan_player_ids else []
        orphan_team_slugs = [
            row[0] for row in self.session.execute(select(Team.canonical_slug).where(Team.id.in_(orphan_team_ids)))
        ] if orphan_team_ids else []

        dangling_alias_ids = [
            row[0]
            for row in self.session.execute(
                select(EntityAlias.id).where(
                    ((EntityAlias.entity_type == "player") & EntityAlias.canonical_slug.in_(orphan_player_slugs))
                    | ((EntityAlias.entity_type == "team") & EntityAlias.canonical_slug.in_(orphan_team_slugs))
                )
            )
        ] if (orphan_player_slugs or orphan_team_slugs) else []

        summary = {
            "orphan_players": len(orphan_player_ids),
            "orphan_teams": len(orphan_team_ids),
            "dangling_entity_aliases": len(dangling_alias_ids),
        }
        if dry_run:
            return summary

        if dangling_alias_ids:
            self.session.execute(delete(EntityAlias).where(EntityAlias.id.in_(dangling_alias_ids)))
        if orphan_player_ids:
            self.session.execute(delete(Player).where(Player.id.in_(orphan_player_ids)))
        if orphan_team_ids:
            self.session.execute(delete(Team).where(Team.id.in_(orphan_team_ids)))
        self.session.commit()
        return summary

    def _entity_status(self, entity_type: str, model, *, limit: int, include_orphans: bool) -> dict[str, Any]:
        all_entities = list(self.session.scalars(select(model).order_by(model.canonical_slug.asc())))
        active_ids = self._active_entity_ids(entity_type)
        if include_orphans:
            entities = all_entities
        else:
            entities = [entity for entity in all_entities if entity.id in active_ids]
        aliases = list(
            self.session.scalars(
                select(EntityAlias)
                .where(EntityAlias.entity_type == entity_type)
                .order_by(EntityAlias.canonical_slug.asc(), EntityAlias.id.asc())
            )
        )

        alias_by_slug: dict[str, dict[str, list[str]]] = defaultdict(lambda: {"source_ids": [], "exact_names": []})
        for alias in aliases:
            bucket = alias_by_slug[alias.canonical_slug]
            if alias.match_kind == "source_id":
                bucket["source_ids"].append(alias.source_key)
            elif alias.match_kind == "exact_name":
                bucket["exact_names"].append(alias.source_key)

        by_normalized_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity in entities:
            by_normalized_name[_normalize_name(entity.display_name)].append(
                {
                    "canonical_slug": entity.canonical_slug,
                    "display_name": entity.display_name,
                    "source_ids": list(entity.source_ids or []),
                }
            )

        suspicious_name_groups = []
        for normalized_name, group in by_normalized_name.items():
            distinct_slugs = {item["canonical_slug"] for item in group}
            if len(distinct_slugs) < 2:
                continue
            suspicious_name_groups.append(
                {
                    "normalized_name": normalized_name,
                    "entities": sorted(group, key=lambda item: item["canonical_slug"]),
                }
            )
        suspicious_name_groups.sort(
            key=lambda item: (-len(item["entities"]), item["normalized_name"])
        )

        canonicals_with_many_aliases = []
        for entity in entities:
            alias_bucket = alias_by_slug[entity.canonical_slug]
            source_ids = sorted(set((entity.source_ids or []) + alias_bucket["source_ids"]))
            exact_names = sorted(set(alias_bucket["exact_names"]))
            variant_count = len(source_ids) + len(exact_names)
            if variant_count < 2:
                continue
            canonicals_with_many_aliases.append(
                {
                    "canonical_slug": entity.canonical_slug,
                    "display_name": entity.display_name,
                    "source_ids": source_ids,
                    "exact_names": exact_names,
                    "variant_count": variant_count,
                }
            )
        canonicals_with_many_aliases.sort(
            key=lambda item: (-item["variant_count"], item["canonical_slug"])
        )

        return {
            "counts": {
                "entities": len(entities),
                "all_entities": len(all_entities),
                "alias_rows": len(aliases),
                "suspicious_name_groups": len(suspicious_name_groups),
                "canonicals_with_many_aliases": len(canonicals_with_many_aliases),
                "include_orphans": include_orphans,
            },
            "suspicious_name_groups": suspicious_name_groups[:limit],
            "canonicals_with_many_aliases": canonicals_with_many_aliases[:limit],
        }

    def _active_entity_ids(self, entity_type: str) -> set[int]:
        if entity_type == "player":
            return {
                row[0]
                for row in self.session.execute(
                    select(EventCompetitor.player_id)
                    .where(EventCompetitor.player_id.is_not(None))
                    .distinct()
                )
            }
        return {
            row[0]
            for row in self.session.execute(
                select(EventCompetitor.team_id)
                .where(EventCompetitor.team_id.is_not(None))
                .distinct()
            )
        }


def _normalize_name(value: str) -> str:
    collapsed = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return collapsed or value.casefold()
