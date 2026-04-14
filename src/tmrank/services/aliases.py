from __future__ import annotations

from dataclasses import dataclass

from tmrank.config_models import AliasEntry, AliasesConfig
from tmrank.utils import slugify


@dataclass(slots=True)
class ResolvedAlias:
    canonical_slug: str
    display_name: str


class AliasResolver:
    def __init__(self, config: AliasesConfig, discovered: AliasesConfig | None = None):
        self._manual_player_by_source_id: dict[str, AliasEntry] = {}
        self._manual_player_by_name: dict[str, AliasEntry] = {}
        self._manual_team_by_source_id: dict[str, AliasEntry] = {}
        self._manual_team_by_name: dict[str, AliasEntry] = {}
        self._discovered_player_by_source_id: dict[str, AliasEntry] = {}
        self._discovered_player_by_name: dict[str, AliasEntry] = {}
        self._discovered_team_by_source_id: dict[str, AliasEntry] = {}
        self._discovered_team_by_name: dict[str, AliasEntry] = {}
        discovered = discovered or AliasesConfig(players=[], teams=[])
        self._register_entries(
            config.players,
            source_index=self._manual_player_by_source_id,
            name_index=self._manual_player_by_name,
        )
        self._register_entries(
            config.teams,
            source_index=self._manual_team_by_source_id,
            name_index=self._manual_team_by_name,
        )
        self._register_entries(
            discovered.players,
            source_index=self._discovered_player_by_source_id,
            name_index=self._discovered_player_by_name,
        )
        self._register_entries(
            discovered.teams,
            source_index=self._discovered_team_by_source_id,
            name_index=self._discovered_team_by_name,
        )

    def resolve_player(self, *, source_id: str | None, exact_name: str | None) -> ResolvedAlias:
        match = self._lookup(
            self._manual_player_by_source_id,
            self._manual_player_by_name,
            self._discovered_player_by_source_id,
            self._discovered_player_by_name,
            source_id,
            exact_name,
        )
        if match:
            return ResolvedAlias(match.canonical_slug, match.display_name)
        display_name = exact_name or source_id or "Unknown Player"
        return ResolvedAlias(slugify(display_name), display_name)

    def resolve_team(self, *, source_id: str | None, exact_name: str | None) -> ResolvedAlias:
        match = self._lookup(
            self._manual_team_by_source_id,
            self._manual_team_by_name,
            self._discovered_team_by_source_id,
            self._discovered_team_by_name,
            source_id,
            exact_name,
        )
        if match:
            return ResolvedAlias(match.canonical_slug, match.display_name)
        display_name = exact_name or source_id or "Unknown Team"
        return ResolvedAlias(slugify(display_name), display_name)

    @staticmethod
    def _register_entries(
        entries: list[AliasEntry],
        *,
        source_index: dict[str, AliasEntry],
        name_index: dict[str, AliasEntry],
    ) -> None:
        for entry in entries:
            for source_id in entry.source_ids:
                source_index[source_id] = entry
            for name in entry.exact_names:
                name_index[name.casefold()] = entry

    @staticmethod
    def _lookup(
        manual_source_index: dict[str, AliasEntry],
        manual_name_index: dict[str, AliasEntry],
        discovered_source_index: dict[str, AliasEntry],
        discovered_name_index: dict[str, AliasEntry],
        source_id: str | None,
        exact_name: str | None,
    ) -> AliasEntry | None:
        if source_id and source_id in manual_source_index:
            return manual_source_index[source_id]
        if exact_name and exact_name.casefold() in manual_name_index:
            return manual_name_index[exact_name.casefold()]
        if source_id and source_id in discovered_source_index:
            return discovered_source_index[source_id]
        if exact_name and exact_name.casefold() in discovered_name_index:
            return discovered_name_index[exact_name.casefold()]
        return None
