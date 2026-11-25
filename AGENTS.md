# AGENTS.md

Shared instructions for coding agents (Claude Code, Codex) working on CityFlow.
Update this file when a convention changes.

## Purpose of the project
CityFlow is a **learning project** run by two physics PhDs preparing for data-science /
risk-modelling roles. Learning matters as much as the result:
- Explain reasoning and name the techniques you use, and why.
- For meaningful design or modelling decisions, lay out the options and let the humans
  choose or write the key part. Don't silently pick.
- Default to explaining and suggesting. Edit files only when explicitly asked,
  after the plan is approved.
- Prefer industry-standard tools and methods over home-grown ones.

## Tools Suggestions
When discussing new steps or refactoring code, analyze the job/code at hand and
suggest better implementations or better tools to achieve the desired goal.
Suggest good behavior for code development and tools commonly used in the
industry. For example tools like: LightGBM (or XGBoost), statsmodels, SHAP,
MLflow, Optuna, pandera, DuckDB, etc...

Please introduce each tool you think it is important to use, summarizing both
the reasoning of your choice and how it compares to alternatives. Provide
examples on how to use and explain what they improve or what are the
advantages.

At most one or two suggestions per step, and only when relevant. Do not pitch a
tool for each little thing.

A tool suggestion is not the same as adding it, the decision is ours.

## Problem definition
- **Task 1 (current):** binary classification. For station `s` at issue time `t`, predict
  `at_risk = bikes_available_to_rent <= 2` at time `t + horizon`.
- **Task 2 (later):** time-to-event: when a station will next become at risk.
- Timestamps are Unix seconds (UTC) in column `time`. Each city's local timezone is in
  `cities.parquet` (`timezone`); use it for hour-of-day / weekday features.
- Any model must beat the persistence baseline on the same evaluation pairs
  with the same label definition.

## Commands
```bash
uv sync                          # install from uv.lock (after every pull that changes it)
uv run ruff check .              # lint
uv run ruff format --check .     # formatting check (drop --check to apply)
uv run pyrefly check             # type check (preset "default")
uv run pytest                    # all tests
uv run pytest -m "not data"      # what CI runs
uv run pre-commit install        # once per clone: ruff on commit, pyrefly on push
```
Run all four checks (ruff check, ruff format --check, pyrefly, pytest) before claiming
something works, and report failures verbatim.

## Repo layout
```
src/city_flow/       # editable package that contains the developed functions
tests/               # pytest; test_<module>.py per module
notebooks/           # exploratory notebooks, numbered NN_topic.ipynb
.github/             # CI, Dependabot, PR template
```

## Data
- European Bike-Sharing Dataset, CC BY-NC 4.0 (non-commercial). ~2.3 GB raw.
- Expected layout: raw CSVs in `data/raw/` (`cities.csv`, `stations.csv`,
  `station_status.csv`, `trips.csv`); per-city Parquet in
  `data/<city>/{cities,stations,station_status,trips}.parquet`.
- `data/` is git-ignored. **Never commit data or derived data.** Keep notebooks under
  1 MB (`check-added-large-files` blocks larger files).
- Git worktrees don't contain `data/`. Don't create a symlink named `data`: the
  `.gitignore` entry `data/` only matches directories, so git would not ignore the
  symlink and it could be committed.
- Status rows look like **change events**, not regular snapshots: no row usually means
  "no change". City-wide silence (e.g. the May 2023 outage) means "unknown".
- Tests must not need the real data. Tests that do are marked `@pytest.mark.data`
  (skipped in CI).

## Conventions
- **uv only.** Never `pip install`; never edit `uv.lock` by hand.
- **New logic gets tests.** Use Hypothesis for invariants (e.g. no look-ahead: features
  at `t` only use rows with `time <= t`; the label equals `bikes(t + horizon) <= 2`).
  Build small synthetic Parquet fixtures in a temp dir, as the existing tests do.
- **Time series: always split by time** (out-of-time validation), never randomly. Leave
  a gap between splits of at least horizon + the longest feature lookback. Flag leakage
  risks.
- **One label definition** in code, reused by baselines, models and analyses.
- **DuckDB:** pass values as `?` parameters, not f-strings.
- Type hints on public functions; docstrings state units and edge cases.
- Line length 88 (ruff). Python 3.14.6.

## Git workflow
- `main` is protected: PR + review + green CI. Never commit to `main`.
- Small, PR-sized branches (`feature/<topic>`, `fix/<topic>`).
- Never push, open a PR, or merge without asking.
- Fill in `.github/pull_request_template.md`.
- CI runs `uv sync --locked`, pre-commit on all files, pyrefly, `pytest -m "not data"`.

## Don't
- Don't commit anything under `data/`, credentials, or `.env` files.
- Don't add dependencies without asking (say what it's for and what the alternatives are).
- Don't edit `.git-blame-ignore-revs`, rewrite pushed history, or force-push.
- Don't use random train/test splits or shuffle-based CV on time-series data.
- Don't change the target, horizon or label rules without an explicit decision.
- Don't rename `persistance.py` or other public modules without asking.
- Don't skip hooks (`--no-verify`) or weaken lint/type settings to make checks pass.
