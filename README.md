# 🚲 CityFlow

**Predicting bike-sharing station shortages using machine learning.**

CityFlow is a data science project aimed at predicting whether a bike-sharing station will have **two or fewer bikes available one hour into the future**.

The project explores data preparation, time-series analysis, feature engineering, classification models, and model evaluation.

## Dataset

We use the **European Bike-Sharing Dataset**, containing historical data from 267 bike-sharing systems across Europe.

- **[Download the complete dataset (ZIP, ~2.3 GB)](https://syncandshare.lrz.de/getlink/fiSKzE1DtkXwB3AUWFFQgy/dataset.zip)**
- [Original GitHub repository](https://github.com/TUMFTM/european-bike-sharing-dataset)

Download and extract the dataset into `data/raw/`.

**Reference:** Waldner et al. (2025), *Data-driven insights into (E-)bike-sharing*, Transportation. [DOI](https://doi.org/10.1007/s11116-025-10661-2).

The dataset is licensed under CC BY-NC 4.0.

## Getting started
After cloning the repo, install `uv` if not already installed (please refer to the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/)).

Once installed, install all dependencies via:
```bash
uv sync
```
This creates `.venv/` with the Python version and dependencies from `uv.lock` and installs `city-flow` in editable mode. Select the `.venv` Python interpreter as your notebook kernel. In Python, import the package as `city_flow`.

Then, install the git hooks (for pre-commit) using:
```bash
uv run pre-commit install
```
which turns on the git hooks, which run formatting and lint checks on every commit.

Furthermore, to have git blame skip the formatting-only commit run:
```bash
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

### After setup

Check that setup worked by running:
```bash
uv run pre-commit run --all-files
```
Every hook should pass.

Add packages via:
```bash
uv add <package>
```
**DO NOT USE PIP**: packages installed that way aren't recorded in `uv.lock`, and the next `uv sync` removes them.

Run code via:
```bash
uv run python <path-to-pyfile>
```

>[!TIP]
> ```bash
> uv run python -m city_flow.data_extraction.extract_cities
> ```

After each `git pull` that changes `uv.lock`, run:
```bash
uv sync
```


## Current Progress

- [x] Dataset extraction and city filtering
- [x] Station-level data quality analysis
- [x] Hourly time-series reconstruction
- [x] Shortage analysis and baseline evaluation
- [x] Exploratory Jupyter notebook
- [ ] Feature engineering and ML model training
- [ ] Model evaluation and comparison
- [ ] Interactive dashboard

## License
Code: [**MIT**](LICENSE).
Dataset: **CC BY-NC 4.0** (see the original dataset).
