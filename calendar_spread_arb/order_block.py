# calendar_spread_arb/order_block.py
# ============================================================
# 套利信號下單邏輯預留區塊
#
# 目前：僅將信號格式化後印到控制台
# 日後：替換 TODO 區塊以接入真實 Shioaji 下單 API
# ============================================================

from typing import Dict, Any
from datetime import datetime, timezone, timedelta

# 台灣標準時間 UTC+8
_TZ_CST = timezone(timedelta(hours=8))


def _fmt_iv(value) -> str:
    """將 IV 值格式化為百分比字串；None 時顯示 N/A 避免以 0 誤導讀者"""
    return f"{value:.4f}" if value is not None else "N/A"


def on_signal(signal: Dict[str, Any]) -> None:
    """
    接收套利信號並執行對應動作。

    Args:
        signal: spread_detector.detect_signal() 回傳的信號字典，
                含 strike / cp / direction / executable_spread 等欄位

    實盤替換指引：
        將下方 TODO 區塊替換為 Shioaji API 呼叫。
    """
    # 必需欄位驗證（防禦性：避免不完整信號造成 KeyError）
    required = ("direction", "strike", "cp", "executable_spread")
    missing = [k for k in required if k not in signal]
    if missing:
        print(f"[order_block] 警告：信號缺少必需欄位 {missing}，略過。")
        return

    now_str = datetime.now(_TZ_CST).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    direction_desc = {
        "BUY_NEAR_SELL_FAR": "買近月 + 賣遠月",
        "BUY_FAR_SELL_NEAR": "買遠月 + 賣近月",
    }.get(signal["direction"], signal["direction"])

    zscore_str = (
        f"{signal['zscore']:.2f}"
        if signal.get("zscore") is not None
        else "N/A（樣本不足）"
    )

    trigger_flags = []
    if signal.get("fixed_triggered"):
        trigger_flags.append(
            f"固定門檻(spread={signal['executable_spread']:+.4f})"
        )
    if signal.get("zscore_triggered"):
        trigger_flags.append(f"z-score({zscore_str}σ)")
    trigger_str = " + ".join(trigger_flags) if trigger_flags else "未知"

    print(
        f"\n{'='*60}\n"
        f"[{now_str}] 套利信號觸發\n"
        f"  商品    : TXO {signal['cp']} {int(signal['strike'])}\n"
        f"  方向    : {direction_desc}\n"
        f"  近月    : {signal.get('near_expiry', '?')}  "
        f"bid IV={_fmt_iv(signal.get('near_iv_bid'))}  "
        f"ask IV={_fmt_iv(signal.get('near_iv_ask'))}\n"
        f"  遠月    : {signal.get('far_expiry', '?')}   "
        f"bid IV={_fmt_iv(signal.get('far_iv_bid'))}  "
        f"ask IV={_fmt_iv(signal.get('far_iv_ask'))}\n"
        f"  可執行IV差: {signal['executable_spread']:+.4f} "
        f"({signal['executable_spread']*100:+.2f}%)\n"
        f"  觸發條件: {trigger_str}\n"
        f"{'='*60}"
    )

    # ========================================================
    # TODO: 在此加入真實下單邏輯
    # ========================================================
    #
    # 範例（需先 import shioaji 並完成登入）：
    #
    # import shioaji as sj
    # from shioaji.constant import Action, TFTOrderType, OrderType
    #
    # if signal["direction"] == "BUY_NEAR_SELL_FAR":
    #     # 買進近月合約（付出 ask 價格）
    #     order_near = api.Order(
    #         price=near_ask_price,
    #         quantity=1,
    #         action=Action.Buy,
    #         price_type=TFTOrderType.LMT,
    #         order_type=OrderType.ROD,
    #     )
    #     # 賣出遠月合約（收取 bid 價格）
    #     order_far = api.Order(
    #         price=far_bid_price,
    #         quantity=1,
    #         action=Action.Sell,
    #         price_type=TFTOrderType.LMT,
    #         order_type=OrderType.ROD,
    #     )
    #     api.place_order(contract_near, order_near)
    #     api.place_order(contract_far,  order_far)
    #
    # ========================================================
    pass
