from tmrank.config_models import AliasesConfig
from tmrank.services.aliases import AliasResolver


def test_alias_resolver_prefers_source_id() -> None:
    resolver = AliasResolver(
        AliasesConfig(
            players=[
                {
                    "canonical_slug": "carljr",
                    "display_name": "Carl Jr.",
                    "source_ids": ["liq:carljr"],
                    "exact_names": ["CarlJr"],
                }
            ],
            teams=[],
        )
    )

    resolved = resolver.resolve_player(source_id="liq:carljr", exact_name="Whatever")
    assert resolved.canonical_slug == "carljr"
    assert resolved.display_name == "Carl Jr."


def test_alias_resolver_falls_back_to_slugified_name() -> None:
    resolver = AliasResolver(AliasesConfig(players=[], teams=[]))

    resolved = resolver.resolve_team(source_id=None, exact_name="Alpha / Beta")
    assert resolved.canonical_slug == "alpha-beta"
    assert resolved.display_name == "Alpha / Beta"


def test_alias_resolver_uses_discovered_aliases_when_yaml_missing() -> None:
    resolver = AliasResolver(
        AliasesConfig(players=[], teams=[]),
        discovered=AliasesConfig(
            players=[
                {
                    "canonical_slug": "scrapie",
                    "display_name": "Scrapie",
                    "source_ids": ["liq:scrapie"],
                    "exact_names": ["Scrapie"],
                }
            ],
            teams=[],
        ),
    )

    resolved = resolver.resolve_player(source_id="liq:scrapie", exact_name="Scrapie")
    assert resolved.canonical_slug == "scrapie"
    assert resolved.display_name == "Scrapie"


def test_alias_resolver_prefers_yaml_over_discovered_aliases() -> None:
    resolver = AliasResolver(
        AliasesConfig(
            players=[
                {
                    "canonical_slug": "carljr",
                    "display_name": "Carl Jr.",
                    "source_ids": ["liq:carljr"],
                    "exact_names": ["Carl Jr."],
                }
            ],
            teams=[],
        ),
        discovered=AliasesConfig(
            players=[
                {
                    "canonical_slug": "carl-jr-old",
                    "display_name": "CarlJR Old",
                    "source_ids": ["liq:carljr"],
                    "exact_names": ["Carl Jr."],
                }
            ],
            teams=[],
        ),
    )

    resolved = resolver.resolve_player(source_id="liq:carljr", exact_name="Carl Jr.")
    assert resolved.canonical_slug == "carljr"
    assert resolved.display_name == "Carl Jr."


def test_alias_resolver_matches_manual_name_variants() -> None:
    resolver = AliasResolver(
        AliasesConfig(
            players=[
                {
                    "canonical_slug": "carljr",
                    "display_name": "Carl Jr.",
                    "source_ids": [],
                    "exact_names": ["Carl Jr.", "Carl_Jr."],
                },
                {
                    "canonical_slug": "bobo247",
                    "display_name": "Bobo247",
                    "source_ids": [],
                    "exact_names": ["Bobo247", "Bobo.247"],
                },
                {
                    "canonical_slug": "mikmos",
                    "display_name": "Mikmos",
                    "source_ids": [],
                    "exact_names": ["Mikmos", "Mik Mos"],
                },
            ],
            teams=[],
        )
    )

    assert resolver.resolve_player(source_id=None, exact_name="Carl_Jr.").canonical_slug == "carljr"
    assert resolver.resolve_player(source_id=None, exact_name="Bobo.247").canonical_slug == "bobo247"
    assert resolver.resolve_player(source_id=None, exact_name="Mik Mos").canonical_slug == "mikmos"
