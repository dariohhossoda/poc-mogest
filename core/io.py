from pathlib import Path
import pandas as pd


_DATE_CANDIDATES = ("date", "data", "datetime", "time", "timestamp")


def load_timeseries(path: str | Path, date_col: str = "date") -> pd.DataFrame:
    df = pd.read_csv(path)
    col_map = {c.lower(): c for c in df.columns}
    for candidate in (date_col, *_DATE_CANDIDATES):
        if candidate.lower() in col_map:
            actual = col_map[candidate.lower()]
            df[actual] = pd.to_datetime(df[actual])
            return df.set_index(actual)
    # fallback: first column treated as date
    first = df.columns[0]
    df[first] = pd.to_datetime(df[first])
    return df.set_index(first)


def load_params(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)
