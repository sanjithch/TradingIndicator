from src.volume import build_volume_profile, high_volume_nodes, price_in_hvn


def make_bar(h, l, c, v):
    return {"t": "2024-01-01T00:00:00Z", "o": l, "h": h, "l": l, "c": c, "v": v}


def test_build_volume_profile_buckets_span_the_price_range():
    bars = [make_bar(h=10, l=10, c=10, v=100), make_bar(h=20, l=20, c=20, v=100)]
    buckets = build_volume_profile(bars, bucket_count=10)
    assert len(buckets) == 10
    assert buckets[0]["low"] == 10
    assert buckets[-1]["high"] == 20
    assert sum(b["volume"] for b in buckets) == 200


def test_build_volume_profile_empty_input():
    assert build_volume_profile([]) == []


def test_build_volume_profile_degenerate_single_price():
    bars = [make_bar(h=10, l=10, c=10, v=50), make_bar(h=10, l=10, c=10, v=25)]
    buckets = build_volume_profile(bars, bucket_count=10)
    assert len(buckets) == 1
    assert buckets[0]["volume"] == 75


def test_high_volume_nodes_picks_top_decile():
    buckets = [{"low": i, "high": i + 1, "volume": v} for i, v in enumerate([1] * 9 + [100])]
    hvns = high_volume_nodes(buckets, percentile=0.9)
    assert len(hvns) == 1
    assert hvns[0]["volume"] == 100


def test_price_in_hvn():
    hvns = [{"low": 10, "high": 11, "volume": 500}]
    assert price_in_hvn(10.5, hvns) is True
    assert price_in_hvn(11, hvns) is False  # half-open interval
    assert price_in_hvn(9.9, hvns) is False
