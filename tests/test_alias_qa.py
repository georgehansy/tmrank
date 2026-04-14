from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tmrank.db.base import Base
from tmrank.db.models import EntityAlias, Player, Team
from tmrank.services.alias_qa import AliasQaService


def test_alias_status_flags_suspicious_player_name_groups() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(canonical_slug="carljr", display_name="Carl Jr.", source_ids=["liq:carljr"]),
                Player(canonical_slug="carl-jr-alt", display_name="CarlJr", source_ids=["liq:carljr-alt"]),
            ]
        )
        session.commit()

        payload = AliasQaService(session).get_status(limit=10, include_orphans=True)
        assert payload["players"]["counts"]["suspicious_name_groups"] == 1
        assert payload["players"]["suspicious_name_groups"][0]["normalized_name"] == "carljr"
        assert [item["canonical_slug"] for item in payload["players"]["suspicious_name_groups"][0]["entities"]] == [
            "carl-jr-alt",
            "carljr",
        ]


def test_alias_status_reports_canonicals_with_many_aliases() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Team(canonical_slug="duo-squad", display_name="Duo Squad", source_ids=["liq:duo-squad"]))
        session.add_all(
            [
                EntityAlias(
                    entity_type="team",
                    source="liquipedia",
                    source_key="Duo Squad",
                    match_kind="exact_name",
                    canonical_slug="duo-squad",
                    display_name="Duo Squad",
                ),
                EntityAlias(
                    entity_type="team",
                    source="liquipedia",
                    source_key="DuoSquad",
                    match_kind="exact_name",
                    canonical_slug="duo-squad",
                    display_name="Duo Squad",
                ),
            ]
        )
        session.commit()

        payload = AliasQaService(session).get_status(limit=10, include_orphans=True)
        assert payload["teams"]["counts"]["canonicals_with_many_aliases"] == 1
        entry = payload["teams"]["canonicals_with_many_aliases"][0]
        assert entry["canonical_slug"] == "duo-squad"
        assert entry["variant_count"] == 3
        assert entry["source_ids"] == ["liq:duo-squad"]
        assert entry["exact_names"] == ["Duo Squad", "DuoSquad"]


def test_alias_status_excludes_orphan_entities_by_default() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(canonical_slug="active-player", display_name="Active Player", source_ids=[]),
                Player(canonical_slug="orphan-player", display_name="Orphan Player", source_ids=[]),
            ]
        )
        session.commit()

        payload = AliasQaService(session).get_status(limit=10)
        assert payload["players"]["counts"]["entities"] == 0
        assert payload["players"]["counts"]["all_entities"] == 2

        payload_with_orphans = AliasQaService(session).get_status(limit=10, include_orphans=True)
        assert payload_with_orphans["players"]["counts"]["entities"] == 2
        assert payload_with_orphans["players"]["counts"]["include_orphans"] is True


def test_cleanup_orphans_removes_entities_and_dangling_aliases() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Player(canonical_slug="orphan-player", display_name="Orphan Player", source_ids=[]),
                Team(canonical_slug="orphan-team", display_name="Orphan Team", source_ids=[]),
                EntityAlias(
                    entity_type="player",
                    source="liquipedia",
                    source_key="Orphan Player",
                    match_kind="exact_name",
                    canonical_slug="orphan-player",
                    display_name="Orphan Player",
                ),
                EntityAlias(
                    entity_type="team",
                    source="liquipedia",
                    source_key="Orphan Team",
                    match_kind="exact_name",
                    canonical_slug="orphan-team",
                    display_name="Orphan Team",
                ),
            ]
        )
        session.commit()

        service = AliasQaService(session)
        dry_run = service.cleanup_orphans(dry_run=True)
        assert dry_run == {
            "orphan_players": 1,
            "orphan_teams": 1,
            "dangling_entity_aliases": 2,
        }

        applied = service.cleanup_orphans(dry_run=False)
        assert applied == dry_run
        assert session.query(Player).count() == 0
        assert session.query(Team).count() == 0
        assert session.query(EntityAlias).count() == 0
