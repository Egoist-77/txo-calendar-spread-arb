# calendar_spread_arb/iv_store.py
# ============================================================
# IV 狀態暫存器
#
# 職責：
#   1. dict 維護每個合約最新 IV（iv_mid / iv_bid / iv_ask）
#   2. 記錄每次更新的時間戳（供 Freshness Guard 使用）
#   3. deque 維護每個 (strike, cp) 的 IV Spread 歷史
#      （用於 rolling z-score 計算）
# ============================================================

import numpy as np
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from calendar_spread_arb import config


class IVStore:
    """
    近/遠月選擇權 IV 的記憶體暫存器

    _iv_data[(expiry_month, strike, cp)]
        → { iv_mid, iv_bid, iv_ask, last_ts }

    _spread_history[(strike, cp)]
        → deque(maxlen=SPREAD_HISTORY_LEN)
    """

    def __init__(self):
        self._iv_data: Dict[tuple, Dict[str, Any]] = {}
        self._spread_history: Dict[tuple, deque] = {}

    def update(
        self,
        expiry_month: str,
        strike: float,
        cp: str,
        iv_mid: Optional[float],
        iv_bid: Optional[float],
        iv_ask: Optional[float],
        ts: datetime
    ) -> None:
        """
        更新指定合約的最新 IV 資料

        Args:
            expiry_month : 到期月份，例如 "202506"
            strike       : 履約價
            cp           : 'C' 或 'P'
            iv_mid/bid/ask: 三種 IV 版本（無法計算時為 None）
            ts           : 此筆報價的時間戳
        """
        key = (expiry_month, float(strike), cp)
        self._iv_data[key] = {
            "iv_mid": iv_mid,
            "iv_bid": iv_bid,
            "iv_ask": iv_ask,
            "last_ts": ts,
        }

    def get(
        self,
        expiry_month: str,
        strike: float,
        cp: str
    ) -> Optional[Dict[str, Any]]:
        """
        取得指定合約的 IV 記錄

        Returns:
            dict with keys: iv_mid, iv_bid, iv_ask, last_ts
            若合約不存在則回傳 None
        """
        return self._iv_data.get((expiry_month, float(strike), cp))

    def is_pair_fresh(
        self,
        near_expiry: str,
        far_expiry: str,
        strike: float,
        cp: str,
        stale_ms: Optional[int] = None
    ) -> bool:
        """
        Freshness Guard：檢查近月與遠月報價是否都在新鮮度視窗內

        防止「鬼訊號」：若其中一方報價已過期，
        用新舊報價混合計算的 IV spread 是虛假的。

        Returns:
            True = 兩方報價都新鮮，可以安全計算 spread
        """
        if stale_ms is None:
            stale_ms = config.STALE_MS

        near_rec = self.get(near_expiry, strike, cp)
        far_rec  = self.get(far_expiry,  strike, cp)

        if near_rec is None or far_rec is None:
            return False

        now = datetime.now(timezone.utc)
        cutoff = timedelta(milliseconds=stale_ms)

        return (now - near_rec["last_ts"]) < cutoff and \
               (now - far_rec["last_ts"])  < cutoff

    def push_spread(self, strike: float, cp: str, spread_value: float) -> None:
        """
        將一個新的 IV spread 值推入對應合約的歷史 deque

        Args:
            spread_value: 本次計算出的可執行 IV spread 值
        """
        key = (float(strike), cp)
        if key not in self._spread_history:
            self._spread_history[key] = deque(maxlen=config.SPREAD_HISTORY_LEN)
        self._spread_history[key].append(spread_value)

    def calc_zscore(
        self,
        strike: float,
        cp: str,
        spread_now: float
    ) -> Optional[float]:
        """
        計算當前 spread 相對於歷史分布的 z-score

        z-score 只在同一 (strike, cp) 的歷史內計算，
        不跨履約價比較（避免 vol smile 結構干擾基準線）

        Returns:
            z-score；樣本不足（< ZSCORE_MIN_SAMPLES）時回傳 None
        """
        key = (float(strike), cp)
        history = self._spread_history.get(key)

        if history is None or len(history) < config.ZSCORE_MIN_SAMPLES:
            return None

        arr = np.array(history, dtype=np.float64)
        mu    = arr.mean()
        sigma = arr.std()

        if sigma < 1e-9:
            return None  # sigma=0 代表歷史資料缺乏波動（流動性極差或掛單未更新），
                         # 視同樣本不足，不觸發信號，避免把資訊真空當作強信號

        return float((spread_now - mu) / sigma)

    def get_contract_count(self) -> int:
        """回傳目前已快取的合約數量（公開介面，取代直接存取 _iv_data）"""
        return len(self._iv_data)
