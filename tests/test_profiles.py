from datetime import datetime, timezone
from pathlib import Path

import pytest
import typer

from tmrank.app_context import DEFAULT_PROFILE_NAME, list_profile_names, profile_label, resolve_profile_config_path
from tmrank.cli import _build_site_manifest, _resolve_export_output_dir, _validate_repo_url
from tmrank.config_models import RatingProfile


def test_resolve_profile_config_path_uses_root_for_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "rating_profile.yml").write_text("initial_mu: 25.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert resolve_profile_config_path(DEFAULT_PROFILE_NAME, "rating_profile.yml") == Path("config/rating_profile.yml")


def test_resolve_profile_config_path_prefers_profile_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "rating_profile.yml").write_text("initial_mu: 25.0\n", encoding="utf-8")
    (tmp_path / "config" / "profiles" / "worldcup-only").mkdir(parents=True)
    (tmp_path / "config" / "profiles" / "worldcup-only" / "rating_profile.yml").write_text(
        "initial_mu: 30.0\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert resolve_profile_config_path("worldcup-only", "rating_profile.yml") == Path(
        "config/profiles/worldcup-only/rating_profile.yml"
    )


def test_resolve_profile_config_path_falls_back_to_root_for_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "majors.yml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "config" / "profiles" / "worldcup-only").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    assert resolve_profile_config_path("worldcup-only", "majors.yml") == Path("config/majors.yml")


def test_resolve_profile_config_path_rejects_unknown_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError):
        resolve_profile_config_path("missing-profile", "rating_profile.yml")


def test_list_profile_names_includes_default_and_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "config" / "profiles" / "worldcup-only").mkdir(parents=True)
    (tmp_path / "config" / "profiles" / "kackiest-kacky").mkdir(parents=True)
    (tmp_path / "config" / "profiles" / "zrt-cups").mkdir(parents=True)
    (tmp_path / "config" / "profiles" / "campaign-only").mkdir(parents=True)
    (tmp_path / "config" / "profiles" / "seasonal-campaign").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    assert list_profile_names() == [
        "default",
        "seasonal-campaign",
        "zrt-cups",
        "worldcup-only",
        "kackiest-kacky",
        "campaign-only",
    ]


def test_resolve_export_output_dir_keeps_default_in_root() -> None:
    assert _resolve_export_output_dir(Path("artifacts"), DEFAULT_PROFILE_NAME) == Path("artifacts")
    assert _resolve_export_output_dir(Path("artifacts"), "seasonal-campaign") == Path("artifacts/seasonal-campaign")


def test_build_site_manifest_tracks_profiles_and_default() -> None:
    generated_at = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
    payload = _build_site_manifest(
        ["default", "seasonal-campaign", "zrt-cups", "worldcup-only", "kackiest-kacky"],
        generated_at,
        "https://github.com/example/repo",
    )

    assert payload["default_profile"] == "default"
    assert payload["repo_url"] == "https://github.com/example/repo"
    assert payload["profiles"] == [
        {"name": "default", "label": "Esports", "path": "default.json", "is_default": True},
        {"name": "seasonal-campaign", "label": "Seasonal Campaign", "path": "seasonal-campaign.json", "is_default": False},
        {"name": "zrt-cups", "label": "ZrT Cups", "path": "zrt-cups.json", "is_default": False},
        {"name": "worldcup-only", "label": "World Cups", "path": "worldcup-only.json", "is_default": False},
        {"name": "kackiest-kacky", "label": "Kacky", "path": "kackiest-kacky.json", "is_default": False},
    ]


@pytest.mark.parametrize(
    "repo_url",
    [
        "javascript:alert(1)",
        "ftp://example.com/repo",
        "/relative/repo",
        "github.com/example/repo",
    ],
)
def test_validate_repo_url_rejects_non_http_urls(repo_url: str) -> None:
    with pytest.raises(typer.BadParameter):
        _validate_repo_url(repo_url)


def test_validate_repo_url_accepts_absolute_http_urls() -> None:
    assert _validate_repo_url("https://github.com/example/repo") == "https://github.com/example/repo"
    assert _validate_repo_url("http://example.test/repo") == "http://example.test/repo"
    assert _validate_repo_url(None) is None


def test_config_models_reject_unknown_keys() -> None:
    with pytest.raises(ValueError, match="extra_forbidden"):
        RatingProfile.model_validate({"initial_mu": 25.0, "initail_sigma": 8.333})


def test_profile_label_uses_short_kacky_name() -> None:
    assert profile_label("default") == "Esports"
    assert profile_label("kackiest-kacky") == "Kacky"
    assert profile_label("zrt-cups") == "ZrT Cups"
    assert profile_label("worldcup-only") == "World Cups"
    assert profile_label("seasonal-campaign") == "Seasonal Campaign"
