# calendar_spread_arb/spread_detector.py
# ============================================================
# IV Spread 信號偵測器
#
# 職責：
#   對每個 (strike, cp) 組合：
#   1. Freshness Guard（防鬼訊號）
#   2. 計算可執行 IV Spread（用 bid/ask，非 mid）
#   3. 固定門檻檢查
#   4. 動態 z-score 門檻檢查（per-strike history）
#   5. 依 SIGNAL_MODE 組合兩個門檻
# ============================================================

from typing import Optional, Dict, Any

from calendar_spread_arb.iv_store import IVStore
from calendar_spread_arb import config


def detect_signal(
    store: IVStore,
    near_expiry: str,
    far_expiry: str,
    strike: float,
    cp: str
) -> Optional[Dict[str, Any]]:
    """
    對指定 (strike, cp) 執行 IV Spread 套利信號偵測

    Args:
        store       : IVStore 實例（含最新 IV 資料與歷史）
        near_expiry : 近月代碼，例如 "202506"
        far_expiry  : 遠月代碼，例如 "202507"
        strike      : 履約價
        cp          : 'C' 或 'P'

    Returns:
        觸發時回傳信號 dict；未觸發回傳 None
    """

    # ==== 步驟 1：Freshness Guard ====
    # 防止用「新近月」對比「舊遠月」產生鬼訊號
    if not store.is_pair_fresh(near_expiry, far_expiry, strike, cp):
        return None

    near = store.get(near_expiry, strike, cp)
    far  = store.get(far_expiry,  strike, cp)

    if near is None or far is None:
        return None

    # 任一方向缺少可執行 IV 則跳過
    if None in (near["iv_bid"], near["iv_ask"], far["iv_bid"], far["iv_ask"]):
        return None

    # ==== 步驟 2：計算可執行 IV Spread ====
    #
    # 方向A：買近月（付 near_ask）+ 賣遠月（收 far_bid）
    spread_buy_near = far["iv_bid"] - near["iv_ask"]

    # 方向B：買遠月（付 far_ask）+ 賣近月（收 near_bid）
    spread_buy_far  = near["iv_bid"] - far["iv_ask"]

    # 選擇利潤較大的方向
    if spread_buy_near >= spread_buy_far:
        executable_spread = spread_buy_near
        direction = "BUY_NEAR_SELL_FAR"
    else:
        executable_spread = spread_buy_far
        direction = "BUY_FAR_SELL_NEAR"

    # ==== 步驟 3：固定門檻檢查 ====
    fixed_triggered = abs(executable_spread) > config.FIXED_THRESHOLD

    # ==== 步驟 4：動態 z-score 門檻 ====
    # 注意順序：先 calc_zscore（用不含本次的歷史計算，語義更正確），
    #           再 push_spread（把本次值推入歷史供下一次計算使用）
    # 若先 push 後 calc，z-score 分母會被本次極端值拉低，造成漏報偏差
    zscore = store.calc_zscore(strike, cp, executable_spread)
    zscore_triggered = (
        zscore is not None and abs(zscore) > config.ZSCORE_THRESHOLD
    )

    # 記錄到歷史（push 在 zscore 計算後，避免自我包含偏差）
    store.push_spread(strike, cp, executable_spread)

    # ==== 步驟 5：組合觸發條件 ====
    if config.SIGNAL_MODE == "AND":
        triggered = fixed_triggered and zscore_triggered
    elif config.SIGNAL_MODE == "OR":
        triggered = fixed_triggered or zscore_triggered
    else:
        # config.py 的 assert 已防止此分支，但明確拋出便於除錯
        raise ValueError(f"未預期的 SIGNAL_MODE 值：{config.SIGNAL_MODE!r}")

    if not triggered:
        return None

    # ==== 回傳信號明細 ====
    return {
        "strike":            float(strike),
        "cp":                cp,
        "near_expiry":       near_expiry,
        "far_expiry":        far_expiry,
        "direction":         direction,
        "executable_spread": executable_spread,
        "mid_spread": (
            far["iv_mid"] - near["iv_mid"]
            if (far.get("iv_mid") is not None and near.get("iv_mid") is not None)
            else None
        ),
        "zscore":            zscore,
        "fixed_triggered":   fixed_triggered,
        "zscore_triggered":  zscore_triggered,
        "near_iv_bid":       near["iv_bid"],
        "near_iv_ask":       near["iv_ask"],
        "far_iv_bid":        far["iv_bid"],
        "far_iv_ask":        far["iv_ask"],
    }
