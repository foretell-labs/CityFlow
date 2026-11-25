# CityFlow analysis plan

A step-by-step plan from raw data to models, with how each step would be built.
Each step lists:

- **Why**: what question it answers, and the technique name to use in interviews.
- **How**: where the code would live and the core of the implementation.
- **Tests**: what to test, including Hypothesis properties where they help.
- **Output**: the table, plot or number the step produces.
- **Decide**: choices for us (the humans) to make, if any.

Steps marked 🧑‍💻 are good candidates for writing the key part ourselves.

Nothing here is decided yet. Code names (modules, functions) are suggestions.

---

## Overview

| Phase | Goal | Depends on open decisions? |
|---|---|---|
| 0 | Data ready and reachable from every checkout | No |
| 1 | Data quality: what to trust, what to exclude | No (it informs them) |
| 2 | Point-in-time modelling table (features + label) | Yes: label rule, horizon |
| 3 | Understand the target (EDA) | Partly |
| 4 | Simple baselines B0–B4 | Yes |
| 5 | Gradient boosting (LightGBM) | Yes |
| 6 | Evaluation harness (used by 4 and 5) | No |
| 7 | Time-to-event (survival analysis) | Yes |
| 8 | Transfer to other cities (stretch) | Yes |

Open decisions (owned by both of us, see `AGENTS.md`):

1. Horizon: 1 h (README) or 2 h (current baseline).
2. Label for maintenance rows and negative counts: exclude, or count as shortage.
3. Which stale or outage periods are not scored.

Phases 1 and 3 produce the evidence for decisions 1 and 3.

Proposed code layout (new pieces marked `+`):

```
src/city_flow/
  config.py            + data_dir(): where the data lives
  labels.py            + the single label definition
  db.py                  fetch_one()
  data_extraction/       extract_cities.py, split_data.py
  inspection/            existing analysis + quality checks (outages, gaps, ...)
  features/            + panel.py (hourly grid), engineering.py (lags, rolling, ...)
  modelling/             persistance.py, + baselines.py, + gbm.py, + survival.py
  evaluation/          + splits.py, metrics.py, bootstrap.py, stability.py
notebooks/
  01_data_exploration.ipynb   (exists)
  02_data_quality.ipynb       Phase 1
  03_target_eda.ipynb         Phase 3
  04_baselines.ipynb          Phases 4 + 6
  05_gradient_boosting.ipynb  Phase 5
  06_survival.ipynb           Phase 7
```

Derived data (the hourly panel, MLflow runs) goes under `data/processed/` and
`mlruns/`, both git-ignored (`mlruns/` would need adding to `.gitignore`).

---

## Phase 0: Data ready

### 0.1 Unpack the raw dataset

- **Why:** on this machine the data is still zipped, and `extract_cities` expects
  CSVs in `data/raw/`.
- **How:** first list the archive's contents (`unzip -l data/full/dataset.zip`) to
  check its folder layout. Then unzip into `data/raw/` so that `cities.csv`,
  `stations.csv`, `station_status.csv` and `trips.csv` sit directly inside it.
- **Output:** `data/raw/*.csv`, then `data/<city>/*.parquet` after running
  `uv run python -m city_flow.data_extraction.extract_cities`.

### 0.2 One place that knows where the data is

- **Why:** git worktrees have no `data/` folder, and paths are currently built
  from `PROJECT_ROOT` in several places.
- **How:** `city_flow/config.py` with `data_dir() -> Path`. It reads the
  environment variable `CITY_FLOW_DATA_DIR` and falls back to `<repo>/data`.
  Notebooks and scripts call `data_dir()` instead of building paths themselves.
- **Tests:** with pytest's `monkeypatch`, set or unset the variable and check
  the returned path.
- **Decide:** environment variable (recommended) or keep the fixed path.

### 0.3 Faster extraction (optional)

- **Why:** `extract_cities` scans the multi-GB `station_status.csv` once per city.
- **How:** a single DuckDB pass that writes all cities at once:
  `COPY (...) TO 'data/by_city' (FORMAT PARQUET, PARTITION_BY (city_id))`.
  This is *partitioned Parquet* (Hive-style folders), a common data-lake layout.

---

## Phase 1: Data quality and filtering

The goal is an **eligibility mask**: for every station and moment, can we trust
the state? Everything later (labels, metrics) uses it.

### 1.1 City-wide outages

- **Why:** when *every* station goes quiet at once, the feed was down and the
  true state is unknown. Currently the May 2023 outage is hard-coded in the
  notebook. Technique: *gap detection on an event stream*.
- **How:** `inspection/outages.py::city_outages(city_dir, min_gap_hours)`. Sort
  all distinct update times for the city and keep the gaps longer than the
  threshold:

  ```sql
  SELECT time AS last_seen, next_time AS resumed
  FROM (
      SELECT time, LEAD(time) OVER (ORDER BY time) AS next_time
      FROM (SELECT DISTINCT time FROM read_parquet(?) WHERE isfinite(time))
  )
  WHERE next_time - time > ? * 3600
  ```

  It returns `(last_seen, resumed)` pairs, the same format
  `shortage_durations(collection_gaps=...)` already accepts.
- **Choosing the threshold:** plot the longest city-wide gap per night. Normal
  quiet nights give the background level; real outages stand well above it.
- **Tests (Hypothesis):** generate sorted update times, insert one gap longer
  than the threshold, and check that:
  - exactly that gap is returned;
  - no update lies strictly inside any returned gap;
  - returned gaps never overlap.
- **Output:** a short table of outages per city, and a timeline plot.

### 1.2 Time between updates, per station

- **Why:** this is the evidence for open decision 3. Is a 17-day silence normal
  for a quiet station, or a dead station? Techniques: *empirical CDF on a log
  scale*, *heavy-tailed distributions*.
- **How:** `inspection/update_gaps.py::station_update_gaps(city_dir, outages)`.
  Per station, `LEAD(time) - time`, dropping intervals that overlap a city
  outage. Plot the ECDF (or the survival function `P(gap > x)`) on a log x-axis,
  split by station size and by hour of day.
- **Physics angle:** if updates were a Poisson process, the gaps would be
  exponential (a straight line on a log-linear survival plot). Bursty usage
  gives heavier tails. How far the data departs from exponential says how
  "bursty" bike demand is.
- **Output:** gap quantiles (50/90/99/99.9%) per station group. A candidate
  staleness rule, e.g. "don't score if the station has been silent longer than
  its own 99.9% quantile while the rest of the city was reporting".
- **Decide:** the staleness rule, together with your co-author.

### 1.3 Are rows change events or snapshots?

- **Why:** the carry-forward logic is only correct if a row is written when
  something changes. This check turns that assumption into a measured fact.
- **How:** per station, compare each row with the previous one. Count the share
  of rows where *nothing* changed (all count columns equal). Mostly "changed"
  means event data, so silence means "no change". Many "unchanged" rows mean
  periodic snapshots, so silence means "missing".
- **Output:** one number per city, which goes into `AGENTS.md` once known.

### 1.4 Station lifetimes

- **Why:** stations are added and removed during the year. Scoring a removed
  station as "healthy" or "short" adds noise.
- **How:** per station, `MIN(time)`, `MAX(time)` and the number of active days.
  Flag stations that appear well after the city's first update, or disappear
  well before its last. Also list stations in `stations.parquet` that never
  report.
- **Output:** each station's active window, used in the eligibility mask.

### 1.5 Maintenance periods

- **Why:** needed for open decision 2, and maintenance may predict shortages.
- **How:** turn the per-row `maintenance` flag into intervals. This is the
  classic SQL *gaps-and-islands* pattern (a common interview question):

  ```sql
  SELECT station_id, maintenance, MIN(time) AS start_time, MAX(time) AS last_row
  FROM (
      SELECT *,
             ROW_NUMBER() OVER (PARTITION BY station_id ORDER BY time)
           - ROW_NUMBER() OVER (PARTITION BY station_id, maintenance ORDER BY time)
             AS island
      FROM read_parquet(?)
  )
  GROUP BY station_id, maintenance, island
  ```

- **Tests:** a hand-written sequence F F T T F T should give the islands
  F, T, F, T with the right boundaries.
- **Output:** how often, how long and which stations; share of time in
  maintenance.

### 1.6 Validation rules

- **Why:** invalid counts must not become labels. Technique: *data contracts /
  schema validation*.
- **How:** with **pandera** (needs approval as a dependency) or plain DuckDB
  checks. Rules:
  - `station_id` not null, `time` finite;
  - counts ≥ 0;
  - `bikes == booked_bikes + bikes_available_to_rent` (record it, don't drop the
    row: about 1% fail in Karlsruhe);
  - no duplicate `(station_id, time)`;
  - `bikes + free_racks == bike_racks` is information only: about 40% of rows
    break it, so racks don't limit returns.
- **Output:** a table of rule × city × share failing. "Hard" failures go into
  the eligibility mask.

### 1.7 Time zones and daylight saving

- **Why:** hour-of-day features in local time break silently on the two
  daylight-saving days each year.
- **How:** keep all storage in UTC. Convert to local time only for calendar
  features, using the city's `timezone`.
- **Tests:** on a daylight-saving date, the local hours of a 24-hour UTC range
  are 23 or 25 distinct values as expected, with no crash or silent shift.

### Phase 1 output: `eligibility`

A function returning, per city, the intervals that are **not** scored: city
outages, station inactive, (depending on decision 2) maintenance, and hard
validation failures. Phase 2 reads it.

---

## Phase 2: The modelling table

### 2.1 One label definition 🧑‍💻

- **Why:** the baseline and the inspection code currently define "at risk"
  differently. One definition, reused everywhere, prevents
  *training–serving skew*.
- **How:** `labels.py` with an `at_risk_sql(...)` builder that returns the SQL
  `CASE` expression, plus a matching Python function for tests. The open
  decisions become parameters, e.g. `maintenance="exclude" | "shortage"`.
  `persistance.py` and `time_analysis.py` then import it.
- **Tests (Hypothesis):** for random `(bikes, maintenance)` values, SQL and
  Python agree, and the label is 1 exactly when the rule says so.

### 2.2 Hourly panel with point-in-time joins

- **Why:** models need one row per station and issue time. Features may only
  use data available at that moment. Technique: *point-in-time correctness /
  as-of joins*.
- **How:** `features/panel.py::build_panel(city_dir, horizon_hours, eligibility)`:
  1. A grid of station × UTC hour over each station's active window.
  2. `ASOF LEFT JOIN` the status rows at the issue time (current state):
     `ON g.station_id = s.station_id AND g.issue_time >= s.time`.
  3. A second as-of join at `issue_time + horizon` for the label.
  4. Columns: `station_id`, `issue_time`, `bikes_now`, `age_now` (seconds since
     the last update), `label`, `eligible`.
  5. Written to `data/processed/<city>/panel_h{horizon}.parquet`.
- **Size:** Heidelberg is about 50 stations × 8,760 h ≈ 440k rows a year, small
  enough for pandas in memory.
- **Decide:** an hourly grid (simple, but weights quiet nights the same as rush
  hour) or issue times sampled at real events. Start with the grid and report
  metrics by hour of day.

### 2.3 Leakage tests 🧑‍💻

These are the most important tests in the project. Properties to check with
Hypothesis, on random event streams (lists of `(time, bikes)`):

1. **Future changes don't move features.** Adding or changing any row with
   `time > t` leaves every feature at `t` unchanged. This is a *metamorphic
   test*: no expected value is needed, only an invariance.
2. **Features only look back.** For every row, the source time of every feature
   is ≤ `issue_time`.
3. **The label is the rule.** `label == rule(as-of state at t + horizon)`.

Sketch of property 1:

```python
@given(past=event_streams(), future=event_streams(), t=issue_times())
def test_features_ignore_the_future(past, future, t):
    later = [(t + 1 + dt, bikes) for dt, bikes in future]  # all strictly after t
    before = build_features(past, issue_times=[t])
    after = build_features(past + later, issue_times=[t])
    assert_frame_equal(before[FEATURES], after[FEATURES])
```

---

## Phase 3: Understanding the target

All of this runs on the training period only, so nothing about the test period
influences modelling choices.

### 3.1 Class balance and change rate

- **How:** share of eligible rows with `label = 1`, by city and station size.
  Also the **change rate**: share of rows where `label != at_risk_now`. That is
  exactly the persistence baseline's error rate, so it is the room a better
  model has to improve.
- **Why:** this decides the metrics. With a 20–30% positive class, accuracy is
  misleading and PR-AUC is informative.

### 3.2 Hour × weekday heatmaps

- **How:** mean label by local hour (rows) × weekday (columns), one heatmap per
  city, using a sequential colour map.
- **Why:** shows daily and weekly patterns (*seasonality*), and which calendar
  features matter.

### 3.3 Differences between stations

- **Why:** some stations are short most of the time, others never. Stations
  with little data give extreme rates by chance. Techniques: *funnel plot*,
  *empirical Bayes shrinkage*.
- **How:**
  - Funnel plot: per-station shortage rate against its number of rows, with
    binomial control limits around the pooled rate. Hours are correlated, so
    the effective sample size is smaller than the row count (worth saying in an
    interview).
  - Empirical Bayes: fit a Beta(α, β) prior to the per-station rates (method of
    moments), then use the shrunk rate `(k + α) / (n + α + β)`. This is the same
    maths as the target encoding in Phase 5.

### 3.4 Transition matrices (Markov view)

- **Why:** P(at risk at t+h | at risk now, hour) is a probabilistic version of
  persistence, and a baseline (B3). Technique: *Markov chain*.
- **How:** from the panel, count transitions between the current state and the
  state at `t + h` for h = 1…6 h, by hour bucket.
- **Physics angle:** test the Markov property with the *Chapman–Kolmogorov
  equation*. If the process is Markov, the 1-hour matrix squared should match
  the measured 2-hour matrix. A mismatch means history matters, which supports
  lag features.

### 3.5 How fast persistence decays

- **How:** agreement between the state now and at `t + h` (for example the phi
  coefficient, or persistence F1) as a function of h from 1 to 24 h.
- **Why:** direct evidence for the 1 h vs 2 h decision. It shows how much
  "free" accuracy persistence gets at each horizon.

### 3.6 How long shortages last 🧑‍💻

- **Why:** the current duration histogram drops episodes cut off by an outage,
  maintenance or the end of the data. That biases durations downward. Technique:
  *Kaplan–Meier estimator with right-censoring*.
- **How:** each episode has a duration and a flag: recovered (event) or cut off
  (censored). The Kaplan–Meier estimate is about 10 lines of numpy, a good one
  to write ourselves before using **lifelines**. Compare small vs big stations
  with a *log-rank test*.
- **Output:** median shortage duration with confidence bands, per group.

---

## Phase 4: Baselines

All models share one interface, so they plug into the same evaluation code:
scikit-learn style `fit(X, y)` and `predict_proba(X)`, fitted on the training
period only.

| # | Model | How | What it shows |
|---|---|---|---|
| B0 | Base rate | Training share of positives | The floor; any model must beat it on Brier |
| B1 | Persistence | `at_risk_now` as a 0/1 "probability" | The current benchmark |
| B2 | Typical history | Mean label per station × local hour × weekday/weekend, shrunk toward the hour-level mean when a cell has few rows | Calendar patterns alone |
| B3 | Markov | P(label \| state now, hour bucket), from training counts with Laplace smoothing | Persistence plus the time of day |
| B4 | Logistic regression | statsmodels `Logit` on `bikes_now`, `at_risk_now`, hour as sin/cos, weekend, station size | An interpretable scorecard |

Notes:

- **B1 and log loss:** a 0/1 prediction that is wrong gives infinite log loss.
  Report Brier score for B1, or clip it to [ε, 1 − ε] and say so.
- **B4 standard errors:** rows are autocorrelated, so default standard errors
  are too small. Use *cluster-robust* standard errors by station or by day
  (`fit(cov_type="cluster", ...)`). A strong interview point.
- **B4 features:** the effect of `bikes_now` is non-linear (0 vs 1 bike matters
  far more than 20 vs 21). Try `log1p(bikes_now)` or splines.

---

## Phase 5: Gradient boosting

### 5.1 Features

Built in DuckDB with window functions on the panel, all point-in-time.

| Group | Examples |
|---|---|
| Current state | `bikes_now`, `at_risk_now`, `age_now` |
| Recent history (lags) | bikes 1, 2, 3, 24 and 168 h ago; change over the last 1 h and 3 h |
| Rolling statistics | mean, std and min of bikes over 3, 6 and 24 h (`RANGE BETWEEN ... PRECEDING`) |
| State duration | hours since the last change of state; hours in the current state |
| Activity | number of updates in the last hour (from raw events, not the grid) |
| Calendar (local time) | hour as sin/cos, weekday, weekend, public holiday (the `holidays` package would need approval) |
| Station | rack count, size group, `place_type`, latitude/longitude |
| Neighbours | share of the k nearest stations (haversine distance) at risk now |
| Station effect | shrunk per-station shortage rate, computed on the training fold only (*target encoding*) |
| Weather (optional) | temperature and rain from an external source such as Open-Meteo, a later decision |

### 5.2 Model

- **LightGBM** binary classifier, with early stopping on a *time-ordered*
  validation fold.
- Start without class weights, which keeps probabilities calibrated. Reweight
  only if needed, then recalibrate.
- Try `station_id` as a native categorical feature against the target encoding.
  The categorical version can overfit.

### 5.3 Tuning, explanation, tracking

- **Optuna:** the objective is the mean walk-forward PR-AUC (or log loss). Keep
  the budget small (50–100 trials).
- **SHAP:** `TreeExplainer` for the global feature ranking and dependence plots,
  e.g. `bikes_now` × hour. Also a leakage alarm: a feature that dominates
  suspiciously should be investigated.
- **MLflow:** local tracking in `mlruns/` (git-ignored). Log parameters,
  metrics, plots and the fitted model for every run.

### 5.4 Calibration

- Check the calibration curve. If needed, recalibrate on a held-out time fold
  with scikit-learn's `CalibratedClassifierCV` around a `FrozenEstimator`, using
  isotonic regression or Platt scaling.

---

## Phase 6: Evaluation

Built first, as soon as Phase 4 starts, then reused for every model.

### 6.1 Walk-forward splits 🧑‍💻

- **Why:** each test fold must be strictly after its training data. Technique:
  *rolling-origin (walk-forward) validation* with *purging*.
- **How:** `evaluation/splits.py::walk_forward_splits(issue_times, ...)`.
  Expanding training window, test windows of e.g. 2 weeks. Training rows whose
  label time (`issue_time + horizon`) falls in the test window are removed
  (the *purge*).
- **Why not `TimeSeriesSplit`:** scikit-learn's version counts its `gap` in
  rows. Our panel has about 50 rows per hour, so the gap must be measured in
  time.
- **Correction to the `AGENTS.md` draft:** the gap needed is **the horizon**,
  not "horizon + longest lookback". Lag features at test time legitimately use
  training-period data (it is the past). What *does* leak is fitting anything
  (target encodings, scalers, shrinkage priors) on data outside the training
  fold.
- **Tests (Hypothesis):** for every fold,
  `max(train issue_time) + horizon <= min(test issue_time)`; folds are ordered
  and test windows don't overlap.

### 6.2 Metrics

`evaluation/metrics.py`, building on the existing `evaluation_metrics`:

| Metric | What it measures |
|---|---|
| PR-AUC (`average_precision_score`) | Ranking quality when shortages are the minority |
| ROC-AUC and **Gini = 2·AUC − 1** | The credit-risk standard |
| Brier score, log loss | Quality of the probabilities |
| Calibration curve | Whether a predicted 30% happens 30% of the time |
| Confusion matrix at the chosen threshold | The existing metrics |

Report every metric on these **slices**:

- all eligible rows;
- **currently healthy** (`at_risk_now = 0`): can the model see a new shortage
  coming? Persistence can't, by construction;
- **currently short** (`at_risk_now = 1`): can it see recoveries?
- by hour of day, city and station size.

The slices only use information known at issue time, so they are fair. Slicing
on "the label changed" would use the answer to choose the rows.

### 6.3 Confidence intervals

- **Why:** rows within a day are correlated, so an ordinary bootstrap gives
  intervals that are too narrow. Technique: *block bootstrap*.
- **How:** resample whole days (or weeks) of the test period with replacement,
  and recompute **the difference** "model − persistence" on each resample. Model
  and baseline are evaluated on the same resampled days (*paired*). The
  improvement is real if the 95% interval of the difference excludes 0.

### 6.4 Stability (PSI)

- **Why:** standard drift monitoring in risk teams. Has the population changed
  between training and test?
- **How:** split the training scores (or a feature) into deciles, and compare
  the shares falling into each decile in the test period:
  `PSI = Σ (actual − expected) · ln(actual / expected)`. Rule of thumb: < 0.1
  stable, 0.1–0.25 moderate shift, > 0.25 large shift.

### 6.5 Threshold from costs

- **How:** set a cost for a missed shortage (a stranded user) and for a false
  alarm (an unnecessary rebalancing trip). Choose the threshold that minimises
  expected cost on the validation folds, and report it once on the test set.
- **Decide:** the cost ratio. It's a product question, a good one to discuss in
  interviews.

### 6.6 Test-set discipline

The final test split is evaluated **once**, at the end, for the chosen models.
All choices are made on the walk-forward validation folds. Each test run is
logged in MLflow so it can't quietly be repeated.

---

## Phase 7: Time-to-event

Question: starting from a healthy station at time t, how long until it becomes
at risk?

### 7.1 Data set-up

- **Landmarking:** at each hourly issue time where the station is healthy,
  start a clock. The event is the first at-risk update. The clock is
  **censored** at an outage, maintenance, station removal or the end of the
  data. Covariates are the Phase 5 features at the landmark time.
- **Alternative:** the time from each recovery to the next shortage. Simpler,
  but less useful for live prediction.

### 7.2 Models, from simple to flexible

| Model | Tool | Notes |
|---|---|---|
| Kaplan–Meier by station group | lifelines | Descriptive; log-rank test between groups |
| Cox proportional hazards | lifelines `CoxPHFitter` | Hazard ratios per covariate. Check proportional hazards with Schoenfeld residuals; time-of-day effects probably need stratifying by hour bucket |
| Discrete-time hazard | statsmodels / LightGBM | One row per station-hour at risk, `y = 1` if the shortage starts that hour. Survival `S(t) = Π (1 − h)` |
| Gradient-boosted / random survival forest | scikit-survival | If the simpler models aren't enough |

The discrete-time hazard model with a 1-hour step **is** the Phase 5
classifier restricted to the "currently healthy" slice. The two tasks share
one modelling table.

### 7.3 Metrics

- Concordance index (C-index): ranking quality of predicted risk.
- Time-dependent Brier score / integrated Brier score.
- Calibration at fixed horizons: predicted P(empty within 1 h) vs observed.

- **Decide:** lifelines (simpler, statistics-oriented) vs scikit-survival
  (scikit-learn API, more ML models, integrated Brier score built in).

---

## Phase 8 (stretch): Other cities

- Train on Heidelberg, test on Karlsruhe and Bergamo (*domain shift*). Only
  city-independent features are allowed: no station IDs or target encodings.
- Compare PSI between cities, and check whether calibration survives the move.
- Karlsruhe allows returning bikes anywhere (`return_to_official_only = False`),
  so station counts may behave differently there.

---

## Dependencies to approve, by phase

| Phase | Package | Group |
|---|---|---|
| 1 | pandera (or plain DuckDB checks) | runtime |
| 3, 7 | lifelines (or scikit-survival) | runtime |
| 4 | statsmodels | runtime |
| 5 | lightgbm, shap, optuna, mlflow | runtime (mlflow could be a dev group) |
| 5 | holidays (optional) | runtime |

## Suggested PR sequence

Each line is roughly one small PR:

1. `config.data_dir()` and replacing `fetchall()[0]` with `fetch_one`.
2. Outage detection and update-gap analysis (1.1–1.3) with notebook 02.
3. Station lifetimes, maintenance intervals, validation rules (1.4–1.7), and
   the eligibility mask.
4. `labels.py`, once decision 2 is made, then the persistence baseline rewired
   to use it.
5. The hourly panel and leakage tests (2.2–2.3).
6. Evaluation harness: splits, metrics, block bootstrap (6.1–6.3).
7. Target EDA (Phase 3) with notebook 03.
8. Baselines B0–B4 (Phase 4) with notebook 04.
9. Features and LightGBM (Phase 5), with MLflow from the first run.
10. Survival analysis (Phase 7).
