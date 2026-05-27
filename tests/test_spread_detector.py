# tests/test_spread_detector.py
import pytest
import sys, os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from calendar_spread_arb.iv_store import IVStore
from calendar_spread_arb.spread_detector import detect_signal
from calendar_spread_arb import config


def _make_store_with_ivs(near_bid, near_ask, far_bid, far_ask,
                          near_fresh=True, far_fresh=True,
                          history_count=0, history_spread=0.02):
    """測試輔助：建立一個有指定 IV 值的 IVStore"""
    store = IVStore()
    now = datetime.now(timezone.utc)
    old = now - timedelta(seconds=2)

    near_ts = now if near_fresh else old
    far_ts  = now if far_fresh  else old

    mid_near = (near_bid + near_ask) / 2
    mid_far  = (far_bid  + far_ask)  / 2

    store.update(config.NEAR_EXPIRY, 17000, "C",
                 iv_mid=mid_near, iv_bid=near_bid, iv_ask=near_ask, ts=near_ts)
    store.update(config.FAR_EXPIRY, 17000, "C",
                 iv_mid=mid_far,  iv_bid=far_bid,  iv_ask=far_ask,  ts=far_ts)

    # 填充 spread 歷史（供 z-score 測試），使用有波動的值避免 sigma=0
    for i in range(history_count):
        store.push_spread(17000, "C", history_spread + (i % 3) * 0.001)

    return store


class TestFreshnessGuardInDetector:
    def test_stale_quote_returns_no_signal(self):
        store = _make_store_with_ivs(
            near_bid=0.18, near_ask=0.20,
            far_bid=0.21,  far_ask=0.23,
            near_fresh=False
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is None


class TestFixedThreshold:
    def test_fixed_threshold_triggered(self):
        # far_bid=0.25 - near_ask=0.20 = 0.05 > 0.02 (FIXED_THRESHOLD)
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.25,  far_ask=0.27
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is not None
        assert result["fixed_triggered"] is True

    def test_fixed_threshold_not_triggered(self):
        # far_bid=0.205 - near_ask=0.20 = 0.005 < 0.02
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.205, far_ask=0.215
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is None or result["fixed_triggered"] is False


class TestZScoreThreshold:
    def test_zscore_not_triggered_without_history(self):
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.205, far_ask=0.215,
            history_count=10  # 不足 30
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is None or result.get("zscore_triggered") is False

    def test_zscore_triggered_with_outlier(self):
        # 歷史 spread 穩定在 0.005，當前 spread 大幅偏離
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.45,  far_ask=0.47,
            history_count=50,
            history_spread=0.005
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is not None
        assert result["zscore_triggered"] is True


class TestSignalContent:
    def test_signal_contains_required_fields(self):
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.25,  far_ask=0.27
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is not None
        required_keys = {
            "strike", "cp", "direction",
            "executable_spread", "fixed_triggered", "zscore_triggered", "zscore"
        }
        assert required_keys.issubset(result.keys())

    def test_direction_buy_near_sell_far(self):
        # far_bid=0.25 - near_ask=0.20 = 0.05（正值，買近月、賣遠月有利）
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.25,  far_ask=0.27
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is not None
        assert result["direction"] == "BUY_NEAR_SELL_FAR"
