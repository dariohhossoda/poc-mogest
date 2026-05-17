from pathlib import Path
import pandas as pd

_DATE_CANDIDATES = ("date", "data", "datetime", "time", "timestamp")


def _read_table(source, **kwargs) -> pd.DataFrame:
    """Read CSV (auto-detect separator) or Excel file."""
    name = getattr(source, "name", str(source))
    if str(name).lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(source, **kwargs)
    else:
        df = pd.read_csv(source, sep=None, engine="python", **kwargs)
    df.columns = df.columns.astype(str)
    return df


def load_timeseries(path, date_col: str = "date") -> pd.DataFrame:
    df = _read_table(path)
    col_map = {c.lower(): c for c in df.columns}
    for candidate in (date_col, *_DATE_CANDIDATES):
        if candidate.lower() in col_map:
            actual = col_map[candidate.lower()]
            df[actual] = pd.to_datetime(df[actual])
            return df.set_index(actual)
    first = df.columns[0]
    df[first] = pd.to_datetime(df[first])
    return df.set_index(first)


def load_params(path) -> pd.DataFrame:
    return _read_table(path)
