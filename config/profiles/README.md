Named config profiles live in `config/profiles/<profile-name>/`.

Each profile directory can override any subset of:

- `tournament_rules.yml`
- `rating_profile.yml`
- `majors.yml`
- `aliases.yml`

Any file that is missing in a named profile falls back to the root `config/` version.

Examples:

- `config/profiles/worldcup-only/tournament_rules.yml`
- `config/profiles/campaign-only/tournament_rules.yml`
- `config/profiles/esports-only/rating_profile.yml`

Use a profile with:

```powershell
tmrank ratings current --profile esports-only
tmrank ratings goat --profile worldcup-only
tmrank export rankings --profile campaign-only
```

List available profiles with:

```powershell
tmrank ratings profiles
```
