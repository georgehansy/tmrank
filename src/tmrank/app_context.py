from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmrank.config_models import AliasesConfig, MajorEventsConfig, RatingProfile, TournamentRulesConfig, load_yaml_model
from tmrank.db.models import EntityAlias
from tmrank.services.aliases import AliasResolver
from tmrank.settings import Settings, get_settings
from tmrank.source.liquipedia import LiquipediaProvider

CONFIG_DIR = Path("config")
PROFILE_CONFIG_DIR = CONFIG_DIR / "profiles"
DEFAULT_PROFILE_NAME = "default"
PROFILE_LABELS = {
    DEFAULT_PROFILE_NAME: "Esports",
    "kackiest-kacky": "Kacky",
    "zrt-cups": "ZrT Cups",
    "worldcup-only": "World Cups",
}
PROFILE_ORDER = [
    DEFAULT_PROFILE_NAME,
    "seasonal-campaign",
    "zrt-cups",
    "worldcup-only",
    "kackiest-kacky",
]


class AppContext:
    def __init__(self, session: Session, settings: Settings, profile_name: str = DEFAULT_PROFILE_NAME):
        self.session = session
        self.settings = settings
        self.profile_name = normalize_profile_name(profile_name)
        self.rules = load_yaml_model(resolve_profile_config_path(self.profile_name, "tournament_rules.yml"), TournamentRulesConfig)
        self.majors = load_yaml_model(resolve_profile_config_path(self.profile_name, "majors.yml"), MajorEventsConfig)
        self.aliases = load_yaml_model(resolve_profile_config_path(self.profile_name, "aliases.yml"), AliasesConfig)
        self.discovered_aliases = _load_discovered_aliases(session)
        self.rating_profile = load_yaml_model(resolve_profile_config_path(self.profile_name, "rating_profile.yml"), RatingProfile)
        self.alias_resolver = AliasResolver(self.aliases, discovered=self.discovered_aliases)
        self.provider = LiquipediaProvider(settings, self.alias_resolver)

    def close(self) -> None:
        self.provider.client.close()


def build_context(session: Session, profile_name: str = DEFAULT_PROFILE_NAME) -> AppContext:
    return AppContext(session=session, settings=get_settings(), profile_name=profile_name)


def normalize_profile_name(profile_name: str | None) -> str:
    normalized = (profile_name or DEFAULT_PROFILE_NAME).strip()
    return normalized or DEFAULT_PROFILE_NAME


def resolve_profile_config_path(profile_name: str | None, filename: str) -> Path:
    normalized = normalize_profile_name(profile_name)
    if normalized == DEFAULT_PROFILE_NAME:
        return CONFIG_DIR / filename
    profile_dir = PROFILE_CONFIG_DIR / normalized
    if not profile_dir.is_dir():
        raise FileNotFoundError(f"Unknown profile '{normalized}'. Expected directory: {profile_dir}")
    profile_path = profile_dir / filename
    return profile_path if profile_path.exists() else CONFIG_DIR / filename


def list_profile_names() -> list[str]:
    discovered = []
    if PROFILE_CONFIG_DIR.is_dir():
        discovered.extend(
            path.name
            for path in PROFILE_CONFIG_DIR.iterdir()
            if path.is_dir()
        )
    profile_names = [DEFAULT_PROFILE_NAME, *discovered]
    order_index = {profile_name: index for index, profile_name in enumerate(PROFILE_ORDER)}
    return sorted(
        profile_names,
        key=lambda profile_name: (
            order_index.get(profile_name, len(PROFILE_ORDER)),
            profile_name,
        ),
    )


def profile_label(profile_name: str) -> str:
    return PROFILE_LABELS.get(profile_name, profile_name.replace("-", " ").title())


def _load_discovered_aliases(session: Session) -> AliasesConfig:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    rows = session.scalars(select(EntityAlias).order_by(EntityAlias.id.asc()))
    for row in rows:
        key = (row.entity_type, row.canonical_slug)
        current = grouped.setdefault(
            key,
            {
                "canonical_slug": row.canonical_slug,
                "display_name": row.display_name,
                "source_ids": [],
                "exact_names": [],
            },
        )
        current["display_name"] = row.display_name
        if row.match_kind == "source_id" and row.source_key not in current["source_ids"]:
            current["source_ids"].append(row.source_key)
        if row.match_kind == "exact_name" and row.source_key not in current["exact_names"]:
            current["exact_names"].append(row.source_key)

    return AliasesConfig(
        players=[
            payload
            for (entity_type, _), payload in grouped.items()
            if entity_type == "player"
        ],
        teams=[
            payload
            for (entity_type, _), payload in grouped.items()
            if entity_type == "team"
        ],
    )
