from tmrank.config_models import AliasesConfig
from tmrank.services.aliases import AliasResolver
from tmrank.settings import Settings
from tmrank.source.liquipedia import LiquipediaProvider


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "DATABASE_URL": "postgresql+psycopg://user:pass@localhost/db",
            "LIQUIPEDIA_API_KEY": "test",
            "LIQUIPEDIA_USER_AGENT": "tmrank-test",
        }
    )


def test_parse_solo_result_row() -> None:
    provider = LiquipediaProvider(_settings(), AliasResolver(AliasesConfig(players=[], teams=[])))
    parsed = provider._parse_event_results(
        "event-1",
        [
            {
                "placement": "2",
                "opponentname": "Bren",
                "opponenttemplate": "liq:bren",
                "prizemoney": "120.00",
            }
        ],
    )
    assert len(parsed.results) == 1
    result = parsed.results[0]
    assert result.placement_low == 2
    assert result.competitor.competitor_type == "player"
    assert result.competitor.canonical_slug == "bren"


def test_parse_team_result_row_uses_member_list() -> None:
    provider = LiquipediaProvider(
        _settings(),
        AliasResolver(
            AliasesConfig(
                players=[{"canonical_slug": "mime", "display_name": "Mime", "exact_names": ["Mime"]}],
                teams=[],
            )
        ),
    )
    parsed = provider._parse_event_results(
        "event-2",
        [
            {
                "placement": "1-2",
                "opponentname": "Duo Squad",
                "extradata": {"players": ["Mime", "Carl Jr."]},
            }
        ],
    )
    result = parsed.results[0]
    assert result.placement_low == 1
    assert result.placement_high == 2
    assert result.competitor.competitor_type == "team"
    assert result.competitor.member_slugs == ["mime", "carl-jr"]


def test_parse_event_results_skips_award_rows_without_placements() -> None:
    provider = LiquipediaProvider(_settings(), AliasResolver(AliasesConfig(players=[], teams=[])))
    parsed = provider._parse_event_results(
        "event-3",
        [
            {
                "pageid": 123,
                "objectname": "123_award_fastest_lap",
                "placement": "",
                "opponentname": "Carl Jr.",
                "prizemoney": 1000,
            },
            {
                "pageid": 123,
                "objectname": "123_ranking_playerone",
                "placement": "1",
                "opponentname": "PlayerOne",
                "prizemoney": 1000,
            },
        ],
    )
    assert len(parsed.results) == 1
    assert parsed.results[0].competitor.display_name == "PlayerOne"


def test_parse_team_result_row_uses_opponentplayers_dict() -> None:
    provider = LiquipediaProvider(_settings(), AliasResolver(AliasesConfig(players=[], teams=[])))
    parsed = provider._parse_event_results(
        "event-4",
        [
            {
                "placement": "1",
                "opponentname": "Duo Squad",
                "opponenttype": "team",
                "opponentplayers": {
                    "p1": "Alpha",
                    "p1dn": "Alpha",
                    "p2": "Beta",
                    "p2dn": "Beta",
                },
            }
        ],
    )
    result = parsed.results[0]
    assert result.competitor.competitor_type == "team"
    assert result.competitor.member_slugs == ["alpha", "beta"]


def test_parse_event_results_deduplicates_same_competitor() -> None:
    provider = LiquipediaProvider(_settings(), AliasResolver(AliasesConfig(players=[], teams=[])))
    parsed = provider._parse_event_results(
        "event-5",
        [
            {
                "placement": "13",
                "opponentname": "Duplicate Player",
                "opponenttemplate": "liq:duplicate-player",
                "prizemoney": 0,
            },
            {
                "placement": "13",
                "opponentname": "Duplicate Player",
                "opponenttemplate": "liq:duplicate-player",
                "prizemoney": 0,
            },
        ],
    )
    assert len(parsed.results) == 1
    assert parsed.results[0].competitor.canonical_slug == "duplicate-player"
