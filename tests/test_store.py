import json

from src.store import export_bars_json, export_levels_json, export_metrics_json, init_db, write_levels, write_signal


def test_store_round_trip(tmp_path):
    db_path = tmp_path / "levels.db"
    conn = init_db(db_path)

    write_levels(
        conn,
        symbol="AAPL",
        run_timestamp="2024-03-01T12:00:00Z",
        current_price=150.0,
        levels=[
            {"price": 145.0, "level_type": "support", "touch_count": 3, "last_touch": "2024-02-28", "in_hvn": True, "score": 13},
            {"price": 155.0, "level_type": "resistance", "touch_count": 2, "last_touch": "2024-02-20", "in_hvn": False, "score": 8},
        ],
    )
    write_signal(
        conn,
        symbol="AAPL",
        run_timestamp="2024-03-01T12:00:00Z",
        current_price=150.0,
        nearest_support=145.0,
        nearest_resist=155.0,
        pct_to_support=0.034,
        pct_to_resist=0.033,
        signal="NEUTRAL",
        suggested_strike=155.0,
    )

    out_path = tmp_path / "levels.json"
    export_levels_json(conn, "2024-03-01T12:00:00Z", out_path)

    payload = json.loads(out_path.read_text())
    assert payload["run_timestamp"] == "2024-03-01T12:00:00Z"
    assert len(payload["symbols"]) == 1
    entry = payload["symbols"][0]
    assert entry["symbol"] == "AAPL"
    assert entry["signal"] == "NEUTRAL"
    assert len(entry["levels"]) == 2

    # append-only: a second run for the same symbol adds rows, doesn't replace
    write_levels(
        conn,
        symbol="AAPL",
        run_timestamp="2024-03-01T16:00:00Z",
        current_price=151.0,
        levels=[{"price": 146.0, "level_type": "support", "touch_count": 2, "last_touch": "2024-03-01", "in_hvn": False, "score": 6}],
    )
    total_rows = conn.execute("SELECT COUNT(*) FROM levels").fetchone()[0]
    assert total_rows == 3


def test_export_metrics_json_tracks_hold_rate_across_runs(tmp_path):
    conn = init_db(tmp_path / "levels.db")
    # run 1: AAPL support at 100
    write_levels(
        conn, "AAPL", "run1", 105.0,
        [{"price": 100.0, "level_type": "support", "touch_count": 2, "last_touch": "t1", "in_hvn": False, "score": 6}],
    )
    # run 2: same support persists (within tolerance) -> held
    write_levels(
        conn, "AAPL", "run2", 106.0,
        [{"price": 100.3, "level_type": "support", "touch_count": 3, "last_touch": "t2", "in_hvn": False, "score": 9}],
    )
    write_signal(conn, "AAPL", "run1", 105.0, 100.0, None, 0.05, None, "NEUTRAL", None)
    write_signal(conn, "AAPL", "run2", 106.0, 100.3, None, 0.057, None, "NEUTRAL", None)

    out_path = tmp_path / "metrics.json"
    export_metrics_json(conn, out_path)
    payload = json.loads(out_path.read_text())

    assert payload["runs"] == ["run1", "run2"]
    assert payload["level_hold_rate_by_run"]["run2"] == 1.0
    assert payload["signal_counts_by_run"]["run1"] == {"NEUTRAL": 1}


def test_export_bars_json_reshapes_for_lightweight_charts(tmp_path):
    bars_by_symbol = {
        "AAPL": [{"t": "2024-01-01T00:00:00+00:00", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}],
        "EMPTY": [],
    }
    out_dir = tmp_path / "bars"
    export_bars_json(bars_by_symbol, out_dir)

    assert (out_dir / "AAPL.json").exists()
    assert not (out_dir / "EMPTY.json").exists()  # nothing to chart, nothing written

    shaped = json.loads((out_dir / "AAPL.json").read_text())
    assert shaped[0]["time"] == 1704067200  # 2024-01-01T00:00:00Z as unix seconds
    assert shaped[0]["close"] == 1.5
