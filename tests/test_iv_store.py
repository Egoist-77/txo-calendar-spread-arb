# tests/test_iv_store.py
import pytest
import sys, os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from calendar_spread_arb.iv_store import IVStore


class TestIVStoreBasic:
    def test_update_and_get(self):
        store = IVStore()
        now = datetime.now(timezone.utc)
        store.update("202506", 17000, "C",
                     iv_mid=0.20, iv_bid=0.19, iv_ask=0.21, ts=now)
        rec = store.get("202506", 17000, "C")
        assert rec is not None
        assert abs(rec["iv_mid"] - 0.20) < 1e-9
        assert abs(rec["iv_bid"] - 0.19) < 1e-9
        assert abs(rec["iv_ask"] - 0.21) < 1e-9

    def test_get_missing_returns_none(self):
        store = IVStore()
        assert store.get("202506", 99999, "C") is None

    def test_update_overwrites(self):
        store = IVStore()
        now = datetime.now(timezone.utc)
        store.update("202506", 17000, "C", 0.20, 0.19, 0.21, now)
        store.update("202506", 17000, "C", 0.25, 0.24, 0.26, now)
        rec = store.get("202506", 17000, "C")
        assert abs(rec["iv_mid"] - 0.25) < 1e-9


class TestFreshnessGuard:
    def test_fresh_quotes_both_recent(self):
        store = IVStore()
        now = datetime.now(timezone.utc)
        store.update("202506", 17000, "C", 0.20, 0.19, 0.21, now)
        store.update("202507", 17000, "C", 0.22, 0.21, 0.23, now)
        assert store.is_pair_fresh("202506", "202507", 17000, "C", stale_ms=500)

    def test_stale_near_month(self):
        store = IVStore()
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=2)
        now    = datetime.now(timezone.utc)
        store.update("202506", 17000, "C", 0.20, 0.19, 0.21, old_ts)
        store.update("202507", 17000, "C", 0.22, 0.21, 0.23, now)
        assert not store.is_pair_fresh("202506", "202507", 17000, "C", stale_ms=500)


class TestSpreadHistory:
    def test_zscore_none_before_min_samples(self):
        store = IVStore()
        for i in range(10):
            store.push_spread(17000, "C", 0.02 + i * 0.001)
        assert store.calc_zscore(17000, "C", 0.03) is None

    def test_zscore_valid_after_min_samples(self):
        """sigma=0 時（全部相同值），應回傳 None"""
        store = IVStore()
        for i in range(50):
            store.push_spread(17000, "C", 0.02)
        z = store.calc_zscore(17000, "C", 0.02)
        assert z is None  # sigma=0，無波動資訊，不觸發信號

    def test_zscore_detects_outlier(self):
        """歷史有真實波動時，離群值應產生高 z-score"""
        store = IVStore()
        # 用有變異的歷史（0.01 ~ 0.03），讓 sigma > 0
        for i in range(50):
            store.push_spread(17000, "C", 0.01 + (i % 3) * 0.01)  # 0.01/0.02/0.03 循環
        z = store.calc_zscore(17000, "C", 0.20)
        assert z is not None
        assert z > 2.0

    def test_zscore_constant_history_returns_none_even_for_outlier(self):
        """歷史全為常數（sigma=0）時，即使當前值偏離，仍回傳 None（資訊真空，不觸發信號）"""
        store = IVStore()
        for _ in range(50):
            store.push_spread(17000, "C", 0.02)
        z = store.calc_zscore(17000, "C", 0.20)
        assert z is None  # sigma=0，視同樣本不足
