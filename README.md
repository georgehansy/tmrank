# tmrank

`tmrank` is a Python 3.12 CLI for building Trackmania ranking views from Liquipedia event history.

It does three main things:

1. syncs and normalizes tournament data from Liquipedia into Postgres
2. computes current-strength and GOAT-style rankings from curated event placements
3. exports JSON for a static GitHub Pages site

This is an independent community project. The rankings are **derived and opinionated**, not official Liquipedia rankings.

## Data and legal notes

- Underlying tournament data is sourced from Liquipedia.
- Liquipedia attribution and API-use notes: [`DATA_ATTRIBUTION.md`](DATA_ATTRIBUTION.md)
- Third-party notices, including `trueskill`: [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
- Repository license: [`LICENSE`](LICENSE)

## Stack

- Python 3.12
- Typer CLI
- SQLAlchemy 2 + psycopg
- Alembic migrations
- httpx
- PyYAML config rules
- `trueskill`

## Environment

Set these before running the CLI:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/tmrank"
$env:LIQUIPEDIA_API_KEY = "your-api-key"
$env:LIQUIPEDIA_USER_AGENT = "tmrank/0.1 (your-contact)"
```

Optional Liquipedia tuning:

```powershell
$env:LIQUIPEDIA_TOURNAMENT_CONDITIONS = "[[liquipediatier::1]] OR [[liquipediatier::2]]"
$env:LIQUIPEDIA_RESULTS_TABLE = "placement"
$env:LIQUIPEDIA_RESULTS_QUERY_FIELDS = "pageid,pagename,objectname,tournament,series,parent,date,placement,prizemoney,weight,mode,type,liquipediatier,opponentname,opponenttemplate,opponenttype,opponentplayers,qualifier,qualifierpage,qualifierurl,extradata"
$env:LIQUIPEDIA_RESULTS_CONDITIONS_TEMPLATE = "[[parent::{source_event_id}]]"
$env:LIQUIPEDIA_REQUEST_SLEEP_SECONDS = "61"
```

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## Initialize the database

```powershell
alembic upgrade head
```

## Core CLI usage

```powershell
tmrank sync tournaments
tmrank sync event-results
tmrank sync all

tmrank ratings current
tmrank ratings goat
tmrank ratings profiles

tmrank export rankings
tmrank export site-data --repo-url https://github.com/<you>/<repo>
```

## Profiles

Named ranking profiles live under `config/profiles/<profile>/`.

The root `config/` files are the `default` profile. Named profiles can override any subset of:

- `tournament_rules.yml`
- `rating_profile.yml`
- `majors.yml`
- `aliases.yml`

Examples:

```powershell
tmrank ratings goat --profile seasonal-campaign
tmrank export rankings --profile seasonal-campaign
tmrank export site-data
```

Current extra profile:

- `seasonal-campaign`

## Site output

The static site lives in `docs/` and is meant for GitHub Pages.

The site reads generated JSON from `docs/data/`, produced by:

```powershell
tmrank export site-data --repo-url https://github.com/<you>/<repo>
```

GitHub Pages can then publish directly from the `docs/` folder on `main`.

## Methodology snapshot

- v1 rates final event placements only
- current rankings use conservative rating (`mu - conservative_multiplier * sigma`)
- GOAT rankings use:
  - prime rating
  - elite area
  - median conservative rating
  - major title points
- all GOAT components are normalized with plain min-max by default
- current rankings use inactivity drift; GOAT uses historical monthly snapshots

## Repo safety

Local secrets and generated data are intentionally excluded from Git:

- `.env`
- local database files
- local artifacts
- virtualenvs and caches
