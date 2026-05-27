# calendar_spread_arb/mock_feed.py
# ============================================================
# 模擬 Shioaji API 的 Tick 報價產生器
#
# 設計重點：
#   - subscribe(callback) / start() / stop() 介面與真實 Shioaji 一致
#   - 日後接入真實 API 只需替換 MockFeed 類別，callback 邏輯不變
#   - 交替產生近月/遠月 Tick，並加入隨機噪音模擬真實市場
# ============================================================

import threading
import time
import random
import math
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from calendar_spread_arb import config
from calendar_spread_arb.iv_engine import bs_price


# ============================================================
# Tick 資料結構
# ============================================================

@dataclass
class TickData:
    """
    單一選擇權 Tick 報價資料

    Attributes:
        symbol       : 商品代碼，例如 "TXO202506C17000"
        expiry_month : 到期月份，例如 "202506"
        strike       : 履約價，例如 17000.0
        cp           : 選擇權類型，'C' = Call，'P' = Put
        last_price   : 最新成交價（點數）
        bid          : 買一價
        ask          : 賣一價
        timestamp    : 報價時間戳（UTC）
    """
    symbol: str
    expiry_month: str
    strike: float
    cp: str
    last_price: float
    bid: float
    ask: float
    spot_price: Optional[float] = None  # 報價時的標的現貨價格（供 IV 計算使用）
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
# 模擬行情產生器
# ============================================================

class MockFeed:
    """
    模擬 Shioaji subscribe 機制的 Tick 報價產生器。

    使用方式（與真實 Shioaji 相同的 callback 介面）：
        feed = MockFeed(spot_price=17000.0)
        feed.subscribe(on_tick)   # 註冊回調函式
        feed.start()              # 開始產生 Tick（非阻塞）
        ...
        feed.stop()               # 停止
    """

    def __init__(self, spot_price: float = None):
        # 使用 is not None 判斷而非 or，避免 spot_price=0 被視為 falsy 而使用預設值
        self._spot = spot_price if spot_price is not None else config.SIMULATED_SPOT
        if self._spot <= 0:
            raise ValueError(f"spot_price 必須大於 0，收到 {self._spot}")
        self._callbacks: List[Callable[[TickData], None]] = []
        self._callbacks_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread = None

        # 為每個合約維護一個緩慢漂移的 IV 基準（模擬 vol smile 結構）
        self._iv_base = self._init_iv_base()

    def _init_iv_base(self) -> dict:
        """初始化每個合約的基準 IV（模擬微笑曲線）"""
        iv_base = {}
        for expiry in [config.NEAR_EXPIRY, config.FAR_EXPIRY]:
            for strike in config.SIMULATED_STRIKES:
                for cp in ['C', 'P']:
                    # 模擬微笑曲線：ATM IV 最低，OTM 較高
                    otm_ratio = abs(strike - self._spot) / self._spot
                    smile_premium = otm_ratio * 0.5
                    # 遠月 IV 通常略高於近月
                    term_premium = 0.02 if expiry == config.FAR_EXPIRY else 0.0
                    base_iv = 0.18 + smile_premium + term_premium
                    iv_base[(expiry, strike, cp)] = base_iv
        return iv_base

    def subscribe(self, callback: Callable[[TickData], None]) -> None:
        """
        註冊 Tick 回調函式（可多次呼叫以訂閱多個處理器）

        Args:
            callback: 接受一個 TickData 參數的函式
        """
        with self._callbacks_lock:
            self._callbacks.append(callback)

    def start(self) -> None:
        """啟動背景執行緒，開始產生模擬 Tick（非阻塞）"""
        if self._stop_event.is_set() is False and self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._generate_loop,
            daemon=True,
            name="MockFeedThread"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止 Tick 產生"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    def _generate_loop(self) -> None:
        """
        主迴圈：交替為近月/遠月的各個合約產生 Tick。
        加入隨機延遲以模擬真實市場的不規則到達。
        """
        interval_s = config.TICK_INTERVAL_MS / 1000.0

        while not self._stop_event.is_set():
            # 隨機漫步更新標的現貨價（模擬指數波動）
            self._spot *= math.exp(random.gauss(0, 0.0001))

            for expiry in [config.NEAR_EXPIRY, config.FAR_EXPIRY]:
                for strike in config.SIMULATED_STRIKES:
                    for cp in ['C', 'P']:
                        if self._stop_event.is_set():
                            return
                        tick = self._make_tick(expiry, float(strike), cp)
                        with self._callbacks_lock:
                            callbacks_snapshot = list(self._callbacks)
                        for cb in callbacks_snapshot:
                            try:
                                cb(tick)
                            except Exception as e:
                                print(f"[MockFeed] callback 發生錯誤：{e}")

            self._stop_event.wait(timeout=interval_s)

    def _make_tick(self, expiry: str, strike: float, cp: str) -> TickData:
        """為指定合約產生一筆模擬 Tick"""
        key = (expiry, strike, cp)

        # IV 隨機漂移（布朗運動型）
        self._iv_base[key] += random.gauss(0, 0.001)
        self._iv_base[key] = max(0.05, min(self._iv_base[key], 2.0))

        sigma = self._iv_base[key]
        S = self._spot

        # 計算到期時間
        T = 30 / 365 if expiry == config.NEAR_EXPIRY else 60 / 365

        # 計算 mid price
        mid = bs_price(sigma, S, strike, T, config.RISK_FREE_RATE, cp)
        mid = max(mid, 1.0)

        # 模擬 bid-ask spread（TXO 真實 spread 約 5~30 點）
        raw_spread = max(5.0, mid * 0.02)
        half = raw_spread / 2.0
        bid = max(1.0, round(mid - half, 0))
        ask = round(mid + half, 0)
        last = round(random.uniform(bid, ask), 0)

        symbol = f"TXO{expiry}{cp}{int(strike)}"
        return TickData(
            symbol=symbol,
            expiry_month=expiry,
            strike=strike,
            cp=cp,
            last_price=last,
            bid=bid,
            ask=ask,
            spot_price=S,
            timestamp=datetime.now(timezone.utc)
        )
