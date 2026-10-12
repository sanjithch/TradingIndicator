"""Refresh data/signal_calibration.json: how VOO actually did after each
macro-tilt state, over the last ~10 years.

    python -m src.calibrate_signal

Needs network (FRED CSV + Yahoo daily bars, both keyless). Re-run it every
few months, or after changing thresholds in config.py. The dashboard shows
these numbers next to the live signal so the sign never overstates itself.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.macro_signal import backtest
from src.market import YAHOO_URL, _http_get

CALIBRATION_PATH = "data/signal_calibration.json"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10,DCOILWTICO"
START = "2016-10-01"


def parse_fred(text: str) -> dict[str, dict[str, float]]:
    """{series_id: {YYYY-MM-DD: value}} from a multi-series FRED CSV;
    blank / '.' cells (holidays, no print) are skipped."""
    out: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        day = row["observation_date"]
        if day < START:
            continue
        for key, raw in row.items():
            if key == "observation_date" or raw in ("", ".", None):
                continue
            out.setdefault(key, {})[day] = float(raw)
    return out


def parse_yahoo_adjclose(payload: dict) -> dict[str, float]:
    result = payload["chart"]["result"][0]
    closes = result["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for ts, c in zip(result["timestamp"], closes):
        if c is not None:
            out[datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()] = float(c)
    return out


def align(voo: dict[str, float], wti: dict[str, float], y10: dict[str, float]):
    days = sorted(set(voo) & set(wti) & set(y10))
    return days, [voo[d] for d in days], [wti[d] for d in days], [y10[d] for d in days]


def run(path: str | Path = CALIBRATION_PATH) -> dict:
    fred = parse_fred(_http_get(FRED_URL, timeout=60))
    voo = parse_yahoo_adjclose(json.loads(_http_get(YAHOO_URL.format(symbol="VOO").replace("range=1d", "range=10y").replace("interval=5m", "interval=1d"), timeout=60)))
    days, v, w, y = align(voo, fred["DCOILWTICO"], fred["DGS10"])
    result = backtest(days, v, w, y)
    result["generated_at"] = datetime.now(timezone.utc).date().isoformat()
    result["sources"] = "VOO adjusted close (Yahoo); WTI spot DCOILWTICO and 10Y DGS10 (FRED)"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    res = run()
    print(f"n={res['n']} {res['first']} -> {res['last']}  baseline={res['baseline']}")
    for state, s in res["states"].items():
        print(f"{state:8s} {s}")
