# calendar_spread_arb/main.py
# ============================================================
# 主程式入口：組裝所有模組並啟動事件驅動的套利監控
#
# 執行方式：
#   cd C:\Users\wu177
#   python -m calendar_spread_arb.main
#
# Ctrl+C 優雅停止
# ============================================================

import time
import signal as _signal
import atexit
from datetime import datetime, timezone, timedelta

# 台灣標準時間 UTC+8
_TZ_CST = timezone(timedelta(hours=8))

import os
from dotenv import load_dotenv

load_dotenv()  # 讀取 .env 檔案（若存在）

from calendar_spread_arb import config
from calendar_spread_arb.mock_feed import MockFeed, TickData
from calendar_spread_arb.iv_engine import calc_all_ivs
from calendar_spread_arb.iv_store import IVStore
from calendar_spread_arb.spread_detector import detect_signal
from calendar_spread_arb.order_block import on_signal

# ---- 全域狀態 ----
_store = IVStore()
_tick_count = 0
_last_display_time = 0.0


def on_tick(tick: TickData) -> None:
    """
    核心 Callback：每次收到新的 Tick 報價時被呼叫

    流程：
      1. 計算三種 IV（iv_mid / iv_bid / iv_ask）
      2. 更新 IVStore
      3. 偵測所有 (strike, cp) 組合的 IV Spread 信號
      4. 有信號時呼叫 on_signal 輸出（預留下單區塊）
    """
    global _tick_count, _last_display_time

    # 計算到期時間（年化）
    T = 30 / 365 if tick.expiry_month == config.NEAR_EXPIRY else 60 / 365

    # 使用 tick 攜帶的即時現貨價（提高 IV 計算精度）；模擬時 fallback 到 config
    S = tick.spot_price if tick.spot_price is not None else config.SIMULATED_SPOT

    # 反推三種 IV
    ivs = calc_all_ivs(
        S=S,
        K=tick.strike,
        T=T,
        r=config.RISK_FREE_RATE,
        cp=tick.cp,
        last_price=tick.last_price,
        bid=tick.bid,
        ask=tick.ask,
    )

    # 更新 IVStore
    _store.update(
        expiry_month=tick.expiry_month,
        strike=tick.strike,
        cp=tick.cp,
        iv_mid=ivs["iv_mid"],
        iv_bid=ivs["iv_bid"],
        iv_ask=ivs["iv_ask"],
        ts=tick.timestamp,
    )

    # 偵測套利信號
    signal = detect_signal(
        store=_store,
        near_expiry=config.NEAR_EXPIRY,
        far_expiry=config.FAR_EXPIRY,
        strike=tick.strike,
        cp=tick.cp,
    )

    if signal is not None:
        on_signal(signal)

    # 每 5 秒顯示一次運行狀態
    _tick_count += 1
    now = time.time()
    if now - _last_display_time >= 5.0:
        _last_display_time = now
        ts_str = datetime.now(_TZ_CST).strftime("%H:%M:%S")
        iv_str = f"iv_mid={ivs['iv_mid']:.4f}" if ivs.get("iv_mid") else "iv_mid=N/A"
        print(
            f"[{ts_str}] 運行中... "
            f"已處理 {_tick_count} 筆 Tick | "
            f"IVStore 合約數：{_store.get_contract_count()} | "
            f"最新：{tick.symbol} bid={tick.bid:.0f} ask={tick.ask:.0f} {iv_str}"
        )


def main():
    print("=" * 60)
    print("台指選擇權 Calendar Spread 套利監控系統")
    print(f"  近月：{config.NEAR_EXPIRY}  遠月：{config.FAR_EXPIRY}")
    print(f"  固定門檻：{config.FIXED_THRESHOLD:.2%}  "
          f"z-score 門檻：{config.ZSCORE_THRESHOLD}")
    print(f"  信號模式：{config.SIGNAL_MODE}")
    print(f"  報價新鮮度視窗：{config.STALE_MS}ms")
    # ── 自動選擇行情來源 ──────────────────────────────────────
    # 有 .env API 金鑰 → 真實 Shioaji；否則 → MockFeed 模擬
    api_key    = os.environ.get("SHIOAJI_API_KEY")
    secret_key = os.environ.get("SHIOAJI_SECRET_KEY")

    if api_key and secret_key:
        from calendar_spread_arb.shioaji_feed import ShioajiFeed
        feed = ShioajiFeed(api_key=api_key, secret_key=secret_key)
        print(f"  行情來源：永豐金 Shioaji API（真實行情）")
    else:
        feed = MockFeed(spot_price=config.SIMULATED_SPOT)
        print(f"  行情來源：MockFeed（模擬行情）")
    print("=" * 60)
    print("按 Ctrl+C 停止\n")

    feed.subscribe(on_tick)

    # 優雅停止
    def handle_stop(sig, frame):
        print(f"\n\n[停止] 共處理 {_tick_count} 筆 Tick，程式結束。")
        feed.stop()
        raise SystemExit(0)

    _signal.signal(_signal.SIGINT, handle_stop)

    feed.start()
    # atexit 確保即使 signal handler 未正確攔截（Windows 環境），程式退出時也能清理執行緒
    atexit.register(feed.stop)

    try:
        while True:
            time.sleep(1)
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
