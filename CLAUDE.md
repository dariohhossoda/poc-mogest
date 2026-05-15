# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

A Python application for rainfall-runoff (chuva-vazão) hydrological modeling using the [`mogestpy`](https://pypi.org/project/mogestpy/) library. The target audience is hydrologists and modeling engineers who need to configure, run, and visualize hydrological process simulations. The app runs in Docker and exposes a web-based UI.

## Tech Stack

- **mogestpy** — core rainfall-runoff modeling engine (PyPI)
- **Streamlit** — primary UI framework (preferred for scientific/engineering dashboards)
- **Docker / Docker Compose** — containerized runtime
- **Python 3.11+**

## Common Commands

```bash
# Build and start
docker compose up --build

# Start without rebuilding
docker compose up

# Run locally (without Docker)
pip install -e ".[dev]"
streamlit run app/main.py

# Tests
pytest

# Single test
pytest tests/test_<module>.py::test_<name> -v

# Lint / format
ruff check .
ruff format .
```

## Project Structure

```
poc/
├── app/
│   ├── main.py          # Streamlit entrypoint
│   ├── pages/           # Multi-page Streamlit pages (one per model/feature)
│   └── components/      # Reusable UI widgets (hydrograph plot, parameter form)
├── core/
│   ├── models.py        # Wrappers around mogestpy model classes
│   ├── io.py            # Reading/writing rainfall-runoff input files
│   └── postprocess.py   # Derived metrics: peak flow, runoff volume, Nash-Sutcliffe
├── tests/
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Architecture Notes

- **`core/`** is UI-agnostic — all mogestpy calls live here. Pages in `app/pages/` import from `core/` and never call mogestpy directly.
- **Streamlit session state** (`st.session_state`) is the persistence layer for a user's active model run. Do not use global variables.
- Model runs can be slow; use `st.spinner` and keep computation off the main thread where possible (Streamlit's `@st.cache_data` or background threads).

## Domain Context

Key hydrological concepts used in this codebase:

| Term | Meaning |
|------|---------|
| Chuva-vazão | Rainfall-runoff — converts precipitation to streamflow |
| Bacia hidrográfica | Watershed / catchment area |
| Hidrograma | Hydrograph — time series of discharge (m³/s) |
| Nash-Sutcliffe (NSE) | Standard model performance metric (1.0 = perfect) |
| Tempo de concentração | Time of concentration — lag from peak rain to peak flow |
| Calibração | Parameter calibration (automated or manual) |

mogestpy models are typically instantiated with a parameter dict and driven by pandas Series of precipitation and, optionally, evapotranspiration. Output is a discharge Series for comparison against observed data.

## Docker

The `Dockerfile` uses a multi-stage build:
1. **builder** — installs dependencies from `pyproject.toml`
2. **runtime** — copies only the installed packages and app code; runs `streamlit run app/main.py --server.port 8501`

`docker-compose.yml` mounts `./data/` into `/app/data/` so users can drop input files (rainfall time series, basin parameters) without rebuilding the image.
