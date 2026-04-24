from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from sqlalchemy.orm import Session

from tmrank.app_context import DEFAULT_PROFILE_NAME, build_context, list_profile_names, profile_label
from tmrank.db.session import session_scope
from tmrank.services.alias_qa import AliasQaService
from tmrank.services.inspect import InspectService
from tmrank.services.ratings import RatingsService
from tmrank.services.sync import SyncService
from tmrank.utils import ensure_dir

app = typer.Typer(help="Trackmania esports data and ratings pipeline.")
sync_app = typer.Typer(help="Liquipedia sync commands.")
ratings_app = typer.Typer(help="Rating commands.")
export_app = typer.Typer(help="Export commands.")
inspect_app = typer.Typer(help="Inspection commands.")
aliases_app = typer.Typer(help="Alias QA commands.")

app.add_typer(sync_app, name="sync")
app.add_typer(ratings_app, name="ratings")
app.add_typer(export_app, name="export")
app.add_typer(inspect_app, name="inspect")
app.add_typer(aliases_app, name="aliases")

PROFILE_OPTION_HELP = (
    "Named config profile. Uses files from config/profiles/<profile>/ and falls back to root config files."
)

def _with_context(profile_name: str = DEFAULT_PROFILE_NAME):
    scope = session_scope()
    session = scope.__enter__()
    try:
        ctx = build_context(session, profile_name=profile_name)
    except FileNotFoundError as exc:
        scope.__exit__(None, None, None)
        raise typer.BadParameter(str(exc), param_hint="--profile") from exc
    return session, ctx, scope


def _parse_iso_date(value: Optional[str], *, option_name: str) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{option_name} must be in YYYY-MM-DD format."
        ) from exc


def _resolve_export_output_dir(output_dir: Path, profile_name: str) -> Path:
    return output_dir if profile_name == DEFAULT_PROFILE_NAME else output_dir / profile_name


def _build_site_manifest(profile_names: list[str], generated_at: datetime, repo_url: Optional[str]) -> dict[str, object]:
    default_profile = DEFAULT_PROFILE_NAME if DEFAULT_PROFILE_NAME in profile_names else profile_names[0]
    return {
        "generated_at": generated_at.isoformat(),
        "default_profile": default_profile,
        "repo_url": _validate_repo_url(repo_url),
        "profiles": [
            {
                "name": profile_name,
                "label": profile_label(profile_name),
                "path": f"{profile_name}.json",
                "is_default": profile_name == default_profile,
            }
            for profile_name in profile_names
        ],
    }


def _validate_repo_url(repo_url: Optional[str]) -> str | None:
    if repo_url is None:
        return None
    parsed = urlparse(repo_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise typer.BadParameter("--repo-url must be an absolute http:// or https:// URL.")
    return repo_url


@sync_app.command("tournaments")
def sync_tournaments(
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        summary = SyncService(session, ctx.provider, ctx.alias_resolver, progress_callback=typer.echo).sync_tournaments()
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo(f"Synced tournaments: seen={summary['seen']} written={summary['written']}")


@sync_app.command("event-results")
def sync_event_results(
    source_event_id: list[str] = typer.Option(
        None,
        "--event",
        "-e",
        help="Only sync results for the selected source event ids.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-fetch results even if the event was already synced before.",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        min=1,
        help="Maximum number of candidate events to sync in this run.",
    ),
    start_date: Optional[str] = typer.Option(
        None,
        "--start-date",
        help="Only consider events ending on or after this date (YYYY-MM-DD).",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="Only consider events ending on or before this date (YYYY-MM-DD).",
    ),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    parsed_start_date = _parse_iso_date(start_date, option_name="--start-date")
    parsed_end_date = _parse_iso_date(end_date, option_name="--end-date")
    session, ctx, scope = _with_context(profile)
    try:
        summary = SyncService(session, ctx.provider, ctx.alias_resolver, progress_callback=typer.echo).sync_event_results_batch(
            source_event_ids=source_event_id or None,
            force=force,
            limit=limit,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        )
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo(
        f"Synced event results: candidates={summary['candidates']} "
        f"seen={summary['seen']} written={summary['written']}"
    )


@sync_app.command("all")
def sync_all(
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-fetch event results even if they were already synced before.",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        min=1,
        help="Maximum number of event result candidates to sync after tournaments.",
    ),
    start_date: Optional[str] = typer.Option(
        None,
        "--start-date",
        help="Only consider events ending on or after this date (YYYY-MM-DD).",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="Only consider events ending on or before this date (YYYY-MM-DD).",
    ),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    parsed_start_date = _parse_iso_date(start_date, option_name="--start-date")
    parsed_end_date = _parse_iso_date(end_date, option_name="--end-date")
    session, ctx, scope = _with_context(profile)
    try:
        summary = SyncService(session, ctx.provider, ctx.alias_resolver, progress_callback=typer.echo).sync_all(
            force=force,
            limit=limit,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        )
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo(json.dumps(summary, indent=2))


@sync_app.command("status")
def sync_status(
    force: bool = typer.Option(
        False,
        "--force",
        help="Preview all matching events, including ones already synced.",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        min=1,
        help="Maximum number of candidate events to show.",
    ),
    start_date: Optional[str] = typer.Option(
        None,
        "--start-date",
        help="Only consider events ending on or after this date (YYYY-MM-DD).",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="Only consider events ending on or before this date (YYYY-MM-DD).",
    ),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    parsed_start_date = _parse_iso_date(start_date, option_name="--start-date")
    parsed_end_date = _parse_iso_date(end_date, option_name="--end-date")
    session, ctx, scope = _with_context(profile)
    try:
        status = SyncService(session, ctx.provider, ctx.alias_resolver).get_results_sync_status(
            force=force,
            limit=limit,
            start_date=parsed_start_date,
            end_date=parsed_end_date,
        )
    finally:
        ctx.close()
        scope.__exit__(None, None, None)

    filters = status["filters"]
    totals = status["totals"]
    typer.echo(
        "results_sync_status "
        f"matching={totals['matching_events']} "
        f"synced={totals['synced_events']} "
        f"unsynced={totals['unsynced_events']} "
        f"start_date={filters['start_date']} "
        f"end_date={filters['end_date']} "
        f"force={filters['force']}"
    )
    typer.echo("next_candidates source_event_id end_date synced_at name")
    for candidate in status["next_candidates"]:
        typer.echo(
            f"next_candidate {candidate['source_event_id']} "
            f"{candidate['end_date']} "
            f"{candidate['results_synced_at']} "
            f"{candidate['name']}"
        )


@ratings_app.command("current")
def current_rankings(
    limit: int = typer.Option(25, min=1),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        rows = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors).compute_current_rankings()[:limit]
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo("rank player rating mu sigma events_24m last_event")
    for row in rows:
        typer.echo(
            f"{row.rank:>4} {row.player_name:<24} {row.conservative_score:>10.4f} "
            f"{row.mu:>8.4f} {row.sigma:>8.4f} {row.recent_events_24_months:>10} {row.last_event_date}"
        )


@ratings_app.command("goat")
def goat_rankings(
    limit: int = typer.Option(25, min=1),
    normalized: bool = typer.Option(
        False,
        "--normalized",
        help="Show normalized 0-1 values for the five GOAT score dimensions.",
    ),
    sqrt_elite_titles: bool = typer.Option(
        False,
        "--sqrt-elite-titles",
        help="Use square-root normalization for elite_area and title_points for comparison.",
    ),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        sqrt_metrics = {"elite_area", "title_points"} if sqrt_elite_titles else None
        rows = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors).compute_goat_rankings(
            sqrt_metrics=sqrt_metrics
        )[:limit]
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    if normalized:
        typer.echo(
            "rank player goat norm_prime norm_elite norm_median norm_titles active_months events"
        )
        for row in rows:
            typer.echo(
                f"{row.rank:>4} {row.player_name:<24} {row.goat_score:>8.4f} "
                f"{row.norm_prime_rating:>10.4f} {row.norm_elite_area:>10.4f} "
                f"{row.norm_median_conservative:>11.4f} "
                f"{row.norm_title_points:>11.4f} {row.active_months:>6} {row.events_played:>6}"
            )
    else:
        typer.echo("rank player goat prime elite_area median titles active_months events")
        for row in rows:
            typer.echo(
                f"{row.rank:>4} {row.player_name:<24} {row.goat_score:>8.4f} "
                f"{row.prime_rating:>8.4f} {row.elite_area:>10.4f} {row.median_conservative:>8.4f} "
                f"{row.title_points:>8.2f} {row.active_months:>6} "
                f"{row.events_played:>6}"
            )


@ratings_app.command("goat-metrics")
def goat_metric_summary(
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        summary = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors).compute_goat_metric_summary()
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo("metric count min p1 p10 median p90 p99 max")
    for metric_name, values in summary.items():
        typer.echo(
            f"{metric_name:<20} {values['count']:>6} {float(values['min']):>10.4f} "
            f"{float(values['p1']):>10.4f} {float(values['p10']):>10.4f} "
            f"{float(values['median']):>10.4f} {float(values['p90']):>10.4f} "
            f"{float(values['p99']):>10.4f} {float(values['max']):>10.4f}"
        )


@ratings_app.command("active-by-month")
def active_by_month(
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        rows = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors).compute_active_players_by_month()
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo("month active_players top10_cutoff p95 p99")
    for row in rows:
        cutoff = f"{row.top10_conservative_cutoff:.4f}" if row.top10_conservative_cutoff is not None else "-"
        p95 = f"{row.p95_conservative:.4f}" if row.p95_conservative is not None else "-"
        p99 = f"{row.p99_conservative:.4f}" if row.p99_conservative is not None else "-"
        typer.echo(f"{row.month} {row.active_players:>6} {cutoff:>12} {p95:>8} {p99:>8}")


@ratings_app.command("tournament-strength")
def tournament_strength(
    year: Optional[int] = typer.Argument(None, help="Optional event end/sort/start year to inspect."),
    limit: int = typer.Option(5, min=1, help="Number of strongest tournaments to show per year."),
    cap: int = typer.Option(16, min=1, help="Average only the strongest N competitors in each event."),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        rows = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors).compute_tournament_strengths(
            year,
            limit=limit,
            cap=cap,
        )
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo("year rank date source_event_id strength cap field effective_field event")
    for row in rows:
        typer.echo(
            f"{row.event_date.year} {row.rank:>4} {row.event_date} {row.source_event_id:<15} {row.strength:>8.4f} "
            f"{row.rated_strength_cap:>3} {row.field_size:>5} {row.effective_field_size:>14} "
            f"{row.event_name}"
        )


@ratings_app.command("rating-leader-timeline")
def rating_leader_timeline(
    limit: Optional[int] = typer.Option(None, min=1),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Show one row per month instead of grouped reign ranges.",
    ),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        service = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors)
        if raw:
            rows = service.compute_rating_leader_timeline_raw()
        else:
            rows = service.compute_rating_leader_timeline()
        if limit is not None:
            rows = rows[:limit]
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    if raw:
        typer.echo("month player conservative")
        for row in rows:
            typer.echo(f"{row.month} {row.player_name:<24} {row.conservative:>8.4f}")
    else:
        typer.echo("start_month end_month months player peak")
        for row in rows:
            typer.echo(
                f"{row.start_month} {row.end_month} {row.months:>6} "
                f"{row.player_name:<24} {row.peak_conservative:>8.4f}"
            )


@ratings_app.command("profiles")
def rating_profiles() -> None:
    for profile_name in list_profile_names():
        typer.echo(profile_name)


@export_app.command("rankings")
def export_rankings(
    output_dir: Path = typer.Option(Path("artifacts")),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        outputs = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors).export_rankings(
            _resolve_export_output_dir(output_dir, profile)
        )
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    for name, path in outputs.items():
        typer.echo(f"{name}: {path}")


@export_app.command("site-data")
def export_site_data(
    output_dir: Path = typer.Option(Path("docs/data")),
    profile: list[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Only export the selected profiles. Defaults to all available profiles.",
    ),
    repo_url: Optional[str] = typer.Option(
        None,
        "--repo-url",
        help="GitHub repository URL to include in the site manifest.",
    ),
) -> None:
    profile_names = profile or list_profile_names()
    generated_at = datetime.now(timezone.utc)
    output_root = ensure_dir(output_dir)
    exported_profiles: list[str] = []

    for profile_name in profile_names:
        session, ctx, scope = _with_context(profile_name)
        try:
            payload = RatingsService(session, ctx.rules, ctx.rating_profile, ctx.majors).build_site_payload(
                profile_name,
                generated_at=generated_at,
            )
        finally:
            ctx.close()
            scope.__exit__(None, None, None)
        profile_path = output_root / f"{profile_name}.json"
        profile_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        exported_profiles.append(profile_name)
        typer.echo(f"profile_json: {profile_path}")

    manifest = _build_site_manifest(exported_profiles, generated_at, repo_url)
    manifest_path = output_root / "site-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"site_manifest: {manifest_path}")


@inspect_app.command("event")
def inspect_event(
    source_event_id: str,
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        payload = InspectService(session).inspect_event(source_event_id)
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo(json.dumps(payload, indent=2, default=str))


@aliases_app.command("status")
def aliases_status(
    limit: int = typer.Option(20, min=1),
    include_orphans: bool = typer.Option(
        False,
        "--include-orphans",
        help="Include unreferenced players/teams in the QA report.",
    ),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        payload = AliasQaService(session).get_status(limit=limit, include_orphans=include_orphans)
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    typer.echo(json.dumps(payload, indent=2, default=str))


@aliases_app.command("cleanup-orphans")
def aliases_cleanup_orphans(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Actually delete orphaned players, teams, and dangling alias rows.",
    ),
    profile: str = typer.Option(DEFAULT_PROFILE_NAME, "--profile", "-p", help=PROFILE_OPTION_HELP),
) -> None:
    session, ctx, scope = _with_context(profile)
    try:
        payload = AliasQaService(session).cleanup_orphans(dry_run=not apply)
    finally:
        ctx.close()
        scope.__exit__(None, None, None)
    mode = "applied" if apply else "dry_run"
    typer.echo(json.dumps({"mode": mode, **payload}, indent=2, default=str))
