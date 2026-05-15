from pathlib import Path
import pandas as pd


def load_timeseries(path: str | Path, date_col: str = "date") -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=[date_col], index_col=date_col)


def load_params(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)
