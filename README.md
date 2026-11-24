# 🚲 CityFlow
[![CI](https://github.com/foretell-labs/CityFlow/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/foretell-labs/CityFlow/actions/workflows/ci.yml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)


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
1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Create the environment (Python version and packages from `uv.lock`):
   ```bash
   uv sync
   ```
3. Download the dataset into `data/raw/` (see [Dataset](#dataset)).
4. Run a pipeline step, or open the notebooks with the `.venv` kernel:
   ```bash
   uv run python -m city_flow.data_extraction.extract_cities
   ```

**Want to contribute?** Read [CONTRIBUTING.md](CONTRIBUTING.md) first. It
describes the full workflow and it includes the one-time setup for git hooks
and notebook stripping, which `uv sync` doesn't do.

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
