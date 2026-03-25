# BroomBroom 🏎️

**F1 analysis and prediction platform** — built for engineers and enthusiasts who want to go deeper than broadcast statistics.

## What it does

| Feature | Description |
|---------|-------------|
| **Race Weekend Explorer** | Browse any F1 race (2018+): results, lap charts, tire strategies, gap-to-leader |
| **Driver Comparison** | Overlay telemetry (speed, brake, throttle, gear) for 2–4 drivers; radar charts; sector dominance; wet/dry delta |
| **Team Analysis** | Constructor pace, straight-line speed, low/high-speed corner performance, tire degradation, pit stop distribution |
| **Circuit Explorer** | Track map with corner classification, historical weather patterns, circuit compatibility per team |
| **Pre-Race Predictions** | Win/podium probability per driver with confidence intervals (LightGBM + DL models) |
| **Race Summary** | Automated post-race report: key moments, overtakes, strategy outcomes, championship impact |
| **Model Lab** | Backtest any model against historical seasons; plug in your own custom predictor |

## Data sources

| Source | Coverage | What it provides |
|--------|----------|-----------------|
| [fastf1](https://github.com/theOehrly/Fast-F1) | 2018+ | Telemetry, lap times, sector times, tire data, weather |
| [jolpica-f1](https://github.com/jolpica/jolpica-f1) | 1950+ | Results, standings, schedules |
| [openf1](https://openf1.org/) | 2023+ | Supplemental telemetry, stints, intervals, race control |

## Quick start

```bash
# 1. Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone and install
git clone https://github.com/brzesiuu/broombroom
cd broombroom
uv sync

# 3. Configure
cp .env.example .env
# Edit .env if you want to change cache directory or log format

# 4. Pre-warm the cache for a season (optional but recommended before first use)
uv run broombroom cache warm --year 2024

# 5. Launch the UI
uv run broombroom serve
# or directly:
uv run streamlit run src/broombroom/ui/app.py
```

### Deep Learning (optional)

```bash
uv sync --extra dl
uv run broombroom train --model transformer_outcome --seasons 2018,2019,2020,2021,2022
```

## Development

```bash
# Run tests (unit only — no network)
uv run pytest -m "not integration and not dl"

# Run with integration tests (requires internet)
uv run pytest -m integration

# Lint + format
uv run ruff check src tests
uv run ruff format src tests

# Type check
uv run pyright

# MLflow UI (view experiment history)
uv run broombroom mlflow ui
```

## CLI reference

```
broombroom cache warm --year YEAR         Pre-fetch and cache all sessions for a season
broombroom cache clear --year YEAR        Remove cached data for a season
broombroom train --model MODEL            Train a prediction model
broombroom model list                     List registered models with backtest scores
broombroom model evaluate --model-file F  Evaluate a custom model against historical data
broombroom model compare A B              Head-to-head backtest comparison
broombroom mlflow ui                      Launch MLflow experiment tracking UI
broombroom summary --year Y --round R     Generate post-race summary
broombroom serve                          Start the Streamlit UI
```

## Architecture

```
src/broombroom/
├── config.py           Central settings (pydantic-settings, BB_ env vars)
├── errors.py           Domain exception hierarchy
├── http.py             Rate-limited httpx client + TokenBucket
├── data/               API adapters, cache, Pydantic models, loaders
├── analysis/           Pure analytical functions (no I/O)
├── prediction/         ML + DL models, feature store, backtesting, registry
├── viz/                Plotly/Matplotlib chart functions (no Streamlit)
├── ui/                 Streamlit pages and components
└── cli/                Typer CLI
```

See [`docs/adr/`](docs/adr/) for architecture decision records.

## Known limitations

- Telemetry available from 2018 only (fastf1 coverage).
- openf1 endpoints cover 2023+ only.
- Prediction models have limited accuracy — small dataset (~3k race-driver samples). Always read the displayed confidence intervals and caveats.
- DL models (LSTM, Transformer) are experimental and may overfit.
- Pre-2023 tire compound designation (C1–C5) is not available via fastf1; only compound type (Soft/Medium/Hard).
