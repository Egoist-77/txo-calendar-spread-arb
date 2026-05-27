# calendar_spread_arb/shioaji_feed.py
# ============================================================
# 永豐金 Shioaji API 行情訂閱器
#
# 介面與 MockFeed 完全相同（subscribe / start / stop），
# 日後若需切換回模擬只需在 main.py 換回 MockFeed 即可。
#
# 訂閱策略：
#   - 使用 QuoteType.BidAsk（BidAskFOPv1）取得 bid/ask 報價
#   - bidask.underlying_price 直接提供現貨即時價，無需另訂 TX 期貨
#   - 每次 BidAsk 更新即觸發一次 TickData callback
# ============================================================

import threading
from datetime import datetime, timezone
from typing import Callable, List, Optional

import shioaji as sj
from shioaji.constant import QuoteType

from calendar_spread_arb.mock_feed import TickData
from calendar_spread_arb import config


class ShioajiFeed:
    """
    永豐金 Shioaji API 行情訂閱器。

    使用方式（與 MockFeed 介面相同）：
        feed = ShioajiFeed(api_key="...", secret_key="...")
        feed.subscribe(on_tick)
        feed.start()   # 登入並開始訂閱（阻塞至登入完成）
        ...
        feed.stop()    # 取消訂閱並登出
    """

    def __init__(self, api_key: str, secret_key: str):
        self._api_key = api_key
        self._secret_key = secret_key
        self._api = sj.Shioaji()
        self._callbacks: List[Callable[[TickData], None]] = []
        self._callbacks_lock = threading.Lock()
        self._stop_event = threading.Event()

        # 現貨參考價（從合約 reference 初始化，BidAsk 進來後即時更新）
        self._spot: float = config.SIMULATED_SPOT

        # 合約對照表：internal_code → (symbol, expiry, strike, cp)
        self._code_to_info: dict = {}

        # ── 必須在 login 前完成 callback 註冊 ──────────────────
        @self._api.on_bidask_fop_v1()
        def _bidask_handler(exchange, bidask):
            self._handle_bidask(exchange, bidask)

    # ── 公開介面 ────────────────────────────────────────────────

    def subscribe(self, callback: Callable[[TickData], None]) -> None:
        """註冊 Tick 回調函式（可多次呼叫）"""
        with self._callbacks_lock:
            self._callbacks.append(callback)

    def start(self) -> None:
        """登入 Shioaji API 並開始訂閱合約（同步登入，訂閱後立即返回）"""
        print("[ShioajiFeed] 登入永豐金 API，請稍候...")
        self._api.login(
            api_key=self._api_key,
            secret_key=self._secret_key,
            fetch_contract=True,
        )
        print("[ShioajiFeed] 登入成功，開始訂閱合約...")
        self._subscribe_contracts()

    def stop(self) -> None:
        """取消所有訂閱並登出"""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        print("[ShioajiFeed] 取消訂閱...")
        for _, contract in list(self._code_to_info.values()):
            try:
                self._api.quote.unsubscribe(
                    contract,
                    quote_type=QuoteType.BidAsk,
                    version=sj.constant.BidAskFOPv1,
                )
            except Exception:
                pass
        try:
            self._api.logout()
            print("[ShioajiFeed] 已登出")
        except Exception as e:
            print(f"[ShioajiFeed] 登出時發生錯誤：{e}")

    # ── 內部方法 ────────────────────────────────────────────────

    def _subscribe_contracts(self) -> None:
        """訂閱 config 中設定的所有近月/遠月合約"""
        success = 0
        fail = 0

        for expiry in [config.NEAR_EXPIRY, config.FAR_EXPIRY]:
            for strike in config.SIMULATED_STRIKES:
                for cp in ["C", "P"]:
                    symbol = f"TXO{expiry}{int(strike)}{cp}"
                    try:
                        contract = self._api.Contracts.Options[symbol]

                        # 第一個合約的 reference 作為現貨初始估計
                        if success == 0 and contract.reference:
                            self._spot = float(contract.reference)

                        # 建立 internal_code → (symbol, contract) 的對照表
                        self._code_to_info[contract.code] = (symbol, contract)

                        self._api.quote.subscribe(
                            contract,
                            quote_type=QuoteType.BidAsk,
                            version=sj.constant.BidAskFOPv1,
                        )
                        success += 1
                    except Exception as e:
                        print(f"[ShioajiFeed] 訂閱失敗 {symbol}：{e}")
                        fail += 1

        print(
            f"[ShioajiFeed] 訂閱完成：成功 {success} 個，"
            f"失敗 {fail} 個（可能履約價不存在）"
        )
        print(f"[ShioajiFeed] 現貨參考價：{self._spot:.0f}")

    def _handle_bidask(self, exchange, bidask) -> None:
        """
        Shioaji BidAskFOPv1 → TickData → 呼叫 callbacks

        BidAskFOPv1 欄位：
            bidask.code             : internal contract code
            bidask.bid_price        : list[float]，[0] 為最佳買價
            bidask.ask_price        : list[float]，[0] 為最佳賣價
            bidask.underlying_price : float，標的現貨即時價
        """
        if self._stop_event.is_set():
            return

        info = self._code_to_info.get(bidask.code)
        if info is None:
            return  # 非我們訂閱的合約，忽略

        symbol, _ = info

        try:
            # 解析 symbol → expiry / strike / cp
            expiry = symbol[3:9]          # e.g. "202606"
            cp     = symbol[-1]           # "C" or "P"
            strike = float(symbol[9:-1])  # e.g. 23600.0

            # 取最佳 bid / ask（有時為 0 表示無報價）
            bid = float(bidask.bid_price[0]) if bidask.bid_price else 0.0
            ask = float(bidask.ask_price[0]) if bidask.ask_price else 0.0

            if bid <= 0.0 or ask <= 0.0:
                return  # 無效報價，跳過（避免 IV 反推失敗）

            # 更新現貨參考價（underlying_price 是即時的）
            if bidask.underlying_price and bidask.underlying_price > 0:
                self._spot = float(bidask.underlying_price)

            mid = (bid + ask) / 2.0

            td = TickData(
                symbol=symbol,
                expiry_month=expiry,
                strike=strike,
                cp=cp,
                last_price=round(mid, 0),
                bid=bid,
                ask=ask,
                spot_price=self._spot,
                timestamp=datetime.now(timezone.utc),
            )

        except Exception as e:
            print(f"[ShioajiFeed] 解析 BidAsk 失敗 ({bidask.code})：{e}")
            return

        # 呼叫已註冊的 callbacks（snapshot 避免鎖競爭）
        with self._callbacks_lock:
            callbacks_snapshot = list(self._callbacks)
        for cb in callbacks_snapshot:
            try:
                cb(td)
            except Exception as e:
                print(f"[ShioajiFeed] callback 發生錯誤：{e}")
