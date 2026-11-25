# Contributing to CityFlow

This page describes how we work on CityFlow: setup, workflow, standards and checks.
For what the project is and the dataset, see the [README](README.md).

---

## 1. One-time setup (per clone)

Some settings live in your local `.git/` folder and are **not** shared by cloning.
Every contributor must run all of these once.

1. **Install uv**: see the [installation guide](https://docs.astral.sh/uv/getting-started/installation/).
2. **Create the environment** (downloads the Python version in `.python-version`
   and installs exactly what's in `uv.lock`, including `city_flow` in editable mode):
   ```bash
   uv sync
   ```
3. **Enable the git hooks** (both `pre-commit` and `pre-push`):
   ```bash
   uv run pre-commit install
   ```
4. **Enable notebook output stripping.** `.gitattributes` declares the filter, but
   each clone must configure it, otherwise git silently commits outputs:
   ```bash
   uv run nbstripout --install
   git config filter.nbstripout.extrakeys "metadata.kernelspec metadata.language_info.version"
   ```
5. **Make `git blame` skip formatting-only commits:**
   ```bash
   git config blame.ignoreRevsFile .git-blame-ignore-revs
   ```
6. **Check that everything works:**
   ```bash
   uv run pre-commit run --all-files
   uv run pytest
   ```

### Editor setup
- **VS Code**: install the **Ruff** (`charliermarsh.ruff`) and **Pyrefly** (`meta.pyrefly`)
  extensions, then *Python: Select Interpreter* → `./.venv`. Both extensions then use the
  tool versions from `.venv`. Under *Python › Analysis: Diagnostics Source*, pick Pylance + Pyrefly
  or remove Pylance and set Pyrefly alone.
  For notebooks, select the `.venv` kernel.
- **Neovim** (optional): to have the editor use the same ruff and pyrefly versions
  as pre-commit and CI, start Neovim with .venv/bin on PATH (`uv run nvim .`, or
  activate `.venv` first). If you install language servers with Mason, set
  `require("mason").setup({ PATH = "append" })`, or Mason's copies take priority.

Rules (lint, format, type checking) live in `pyproject.toml`, **never** in editor
settings, so every editor and CI apply the same ones.

---

## 2. Workflow

```
issue → branch → commits → push → pull request → CI + review → merge
```

1. **Start from an issue.** Every piece of work has a GitHub issue. Create the branch
   from the issue page (*Development → Create a branch*). Branch names follow
   `<issue-number>-<short-description>`, e.g. `16-test-correlation-among-data`.
2. **Never commit directly to `main`.**
3. **Keep pull requests small and about one topic.** Refactors, renames and formatting
   go in separate pull requests from behaviour changes.
4. **Open a pull request** and fill in the template. Link the issue with
   `Closes #<number>` or `Resolves #<number>` so it closes automatically on merge.
5. **Merge requirements:** CI is green and the other person has approved.
6. **Merge with "Create a merge commit".**
7. **After merging:** delete the branch, then update your local copy:
   ```bash
   git switch main && git pull && uv sync
   ```
8. **Bring `main` into a long-lived branch** regularly so conflicts stay small.
   ```bash
   git switch <long-lived-branch>
   git merge main
   ```

### Commit messages
- Imperative, present tense, about 50 characters (max 72): `Add confusion matrix to persistence baseline`
- One logical change per commit. Explain *why* in the body if it isn't obvious.

### Formatting-only changes
Mass reformatting (e.g. after changing ruff settings) gets its **own pull request**,
containing nothing else. After it's merged:
1. Copy the commit's ID **as it appears on `main`** (`git log --oneline`).
2. Add it to `.git-blame-ignore-revs` with a comment, in a follow-up pull request.

---

## 3. Project layout

```
src/city_flow/            # the installable package: all reusable logic lives here
tests/                    # pytest tests, mirroring the package structure
notebooks/                # exploration only; import from city_flow, don't define logic here
data/                     # local dataset (git-ignored, never committed)
```

- Import the package as `city_flow` (`from city_flow.inspection import trips`), never via `src.`.
- Run modules with `uv run python -m city_flow.<module>`.

---

## 4. Dependencies

- Add with uv, **never with `pip`**. `pip` installs aren't recorded in `uv.lock`, and the
  next `uv sync` removes them.
  ```bash
  uv add <package>                    # runtime dependency
  uv add --group test <package>       # groups: lint, test, notebook
  ```
- Only list packages **your code imports directly**. Their dependencies are handled
  by the lock.
- Always commit `pyproject.toml` **and** `uv.lock` together. The `uv-lock` hook fails
  if they're out of sync.
- After pulling a change to `uv.lock`, run `uv sync`.

---

## 5. Code standards

| Tool | Enforces | Configured in |
|---|---|---|
| ruff (lint) | likely bugs, import order, modern syntax | `[tool.ruff.lint]` |
| ruff (format) | layout and style | `[tool.ruff.format]` |
| pyrefly | type correctness (`preset = "default"`) | `[tool.pyrefly]` |

- Add type hints to every function in `src/city_flow/`.
- Handle "no result" cases explicitly. For single-row `DuckDB` queries use
  `city_flow.db.fetch_one`, which raises a clear error instead of returning `None`.
- Don't depend on the current working directory: build paths from a project-root
  constant, not from where the script was started.
- Don't silence a checker (`# noqa`, `# pyrefly: ignore`) without a short comment
  explaining why.

---

## 6. Tests

We use **pytest**, plus **Hypothesis** for property-based tests.

```bash
uv run pytest                 # all tests
uv run pytest -x -k trips     # stop at first failure, only tests matching "trips"
uv run pytest --cov           # with coverage report
uv run pytest -m "not data"   # what CI runs
```

- Tests live in `tests/test_<module>.py`, and test functions are named `test_<behaviour>`.
- Use **tiny hand-made data** (a few rows), built with the `tmp_path` fixture.
  Tests must never need the real dataset, unless they're marked as below.
- **Markers** (declared in `pyproject.toml`; unknown markers are an error):
  - `@pytest.mark.data`: needs the real dataset in `data/`. Skipped in CI.
  - `@pytest.mark.slow`: takes more than a few seconds.
- Shared fixtures go in `tests/conftest.py`. It already forces `matplotlib`'s
  non-interactive backend, so plotting tests run headless.
- **What to test first:** data transformations. Things like no look-ahead leakage,
  correct lag direction, train/test split by time, no duplicate timestamps, and
  edge cases such as empty inputs.
- **Hypothesis** is for invariants that must hold for *any* input.
- **Every bug fix comes with a test that fails before the fix.**

---

## 7. Notebooks

- Notebooks are for exploration and presentation. **Logic goes in `city_flow`**, and the
  notebook imports it, so the logic is tested and reusable.
- Outputs are stripped from commits automatically by the `nbstripout` filter (setup step 4).
  Your local copy keeps its outputs.
- Don't keep `_old` / `_v2` copies. Git history is the version history.
- Ruff lints and formats notebooks too.

---

## 8. Data

- **Never commit data.** `data/` is git-ignored, and a hook blocks any file over 1 MB.
- Expected location: extract the dataset into `data/raw/` (see [README](README.md)).
- The dataset is licensed **CC BY-NC 4.0** (non-commercial). Our code is [MIT](LICENSE), but any
  derived data or trained models we publish must respect the dataset's terms.
- Never commit secrets. Use a `.env` file (git-ignored) and commit a `.env.example` with
  fake values.

---

## 9. Checks: what runs where

| When | What runs | Can be skipped? |
|---|---|---|
| Editor (on save) | ruff, pyrefly | yes, it's only for convenience |
| `git commit` | file hygiene, `uv-lock`, ruff check + format | technically (`--no-verify`), but **don't** |
| `git push` | pyrefly | technically, but **don't** |
| Pull request (CI) | `uv sync --locked`, all pre-commit hooks, pyrefly, `pytest -m "not data"` | **no**: required to merge |

Run everything CI runs, locally:
```bash
uv run pre-commit run --all-files && uv run pyrefly check && uv run pytest -m "not data"
```

**When a hook fails:**
- *"files were modified by this hook"*: the hook fixed something for you. Look at the
  change (`git diff`), stage it, and commit again.
- *errors remaining*: fix them by hand. Ask in the pull request if a rule seems wrong;
  changing a rule is a decision for both of us, made in its own pull request.

**When CI fails:** open the ❌ on the pull request → the failing step → read the log.
Reproduce it locally with the commands above.

---

## 10. Dependabot pull requests

Dependabot opens grouped pull requests every month for Python packages (`uv.lock`),
GitHub Actions and pre-commit hook versions, waiting a few days after each release.

1. Read the linked release notes for anything marked breaking or deprecated.
2. Wait for CI. **Green**: approve and merge. **Red**: fix our code on that branch, or
   close the pull request and comment `@dependabot ignore this major version`.
3. Don't merge a red Dependabot pull request "to fix later".

---

## 11. Questions

Open an issue or comment on the relevant pull request. Decisions about tooling and
conventions are recorded in pull requests, so they're easy to find later.
