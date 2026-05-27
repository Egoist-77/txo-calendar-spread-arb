# calendar_spread_arb/iv_engine.py
# ============================================================
# Black-Scholes 選擇權定價引擎
# 核心計算使用純 math 模組（不依賴 scipy），低延遲設計
# Newton-Raphson 反推 IV：利用 vega 作為梯度，3-5 次收斂
# 失敗時 fallback 到 scipy.optimize.brentq（可靠性保底）
# ============================================================

import math
from typing import Optional

_SQRT_2PI = math.sqrt(2 * math.pi)
_SQRT2    = math.sqrt(2)


def _norm_cdf(x: float) -> float:
    """標準常態分布累積分布函數（CDF），使用 math.erf 取代 scipy"""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _norm_pdf(x: float) -> float:
    """標準常態分布概率密度函數（PDF）"""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def bs_price(sigma: float, S: float, K: float, T: float,
             r: float, cp: str) -> float:
    """
    Black-Scholes 歐式選擇權理論價格

    Args:
        sigma : 年化波動率（例：0.20 = 20%）
        S     : 標的現貨價格
        K     : 履約價
        T     : 到到期日的年化時間（例：30天 = 30/365）
        r     : 無風險年化利率
        cp    : 'C' = Call，'P' = Put

    Returns:
        選擇權理論價格（與 S 同單位）
    """
    if T <= 0 or sigma <= 0:
        if cp == 'C':
            return max(0.0, S - K)
        else:
            return max(0.0, K - S)

    if S <= 0 or K <= 0:
        raise ValueError(f"S 和 K 必須為正數，收到 S={S}, K={K}")

    if cp not in ('C', 'P'):
        raise ValueError(f"cp 必須為 'C' 或 'P'，收到 {cp!r}")

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    discount = math.exp(-r * T)

    if cp == 'C':
        return S * _norm_cdf(d1) - K * discount * _norm_cdf(d2)
    else:
        return K * discount * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_vega(sigma: float, S: float, K: float, T: float, r: float) -> float:
    """
    Black-Scholes Vega（∂期權價格 / ∂σ）

    在 Newton-Raphson 迭代中作為梯度使用。
    Vega 對 Call 和 Put 相同。

    Returns:
        Vega 值；T=0 或 sigma=0 時回傳 0.0
    """
    if T <= 0 or sigma <= 0:
        return 0.0

    if S <= 0 or K <= 0:
        raise ValueError(f"S 和 K 必須為正數，收到 S={S}, K={K}")

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * _norm_pdf(d1) * math.sqrt(T)


def calc_iv_newton(
    option_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    cp: str,
    initial_sigma: float = 0.30,
    max_iter: int = 50,
    tol: float = 1e-6
) -> Optional[float]:
    """
    以 Newton-Raphson 法反推隱含波動率（IV）

    迭代公式：σ_{n+1} = σ_n + (市場價格 - BS理論價格) / Vega
    典型收斂速度：3~5 次迭代

    Returns:
        反推出的 IV；失敗時回傳 None
    """
    if option_price <= 0 or T <= 0:
        return None

    if S <= 0 or K <= 0:
        return None

    intrinsic = max(0.0, (S - K) if cp == 'C' else (K - S))
    if option_price < intrinsic - 0.5:
        return None

    sigma = initial_sigma

    for _ in range(max_iter):
        price_bs = bs_price(sigma, S, K, T, r, cp)
        vega_bs  = bs_vega(sigma, S, K, T, r)

        if abs(vega_bs) < 1e-10:
            break

        diff = option_price - price_bs
        if abs(diff) < tol:
            return sigma

        sigma = sigma + diff / vega_bs
        sigma = max(1e-4, min(sigma, 10.0))

    return _brentq_fallback(option_price, S, K, T, r, cp)


def _brentq_fallback(
    option_price: float, S: float, K: float,
    T: float, r: float, cp: str
) -> Optional[float]:
    """scipy.optimize.brentq 作為 Newton-Raphson 失敗時的保底方案"""
    try:
        from scipy.optimize import brentq
        objective = lambda s: bs_price(s, S, K, T, r, cp) - option_price
        lo, hi = 1e-4, 10.0
        if objective(lo) * objective(hi) > 0:
            return None
        return brentq(objective, lo, hi, xtol=1e-6, maxiter=200)
    except ImportError:
        return None
    except Exception:
        return None


def calc_all_ivs(
    S: float, K: float, T: float, r: float, cp: str,
    last_price: float, bid: float, ask: float
) -> dict:
    """
    計算選擇權的三種 IV 版本：
    - iv_mid  : 以 (bid+ask)/2 計算，理論參考值
    - iv_bid  : 以 bid 計算（賣出方收到的 IV）
    - iv_ask  : 以 ask 計算（買進方付出的 IV）
    - iv_last : 以最新成交價計算

    套利信號應使用 iv_bid / iv_ask（可執行 IV）

    Returns:
        dict，包含 iv_mid / iv_bid / iv_ask / iv_last 四個鍵。
        任一 IV 無法計算（option_price <= 0、S/K <= 0 或無法收斂）時，對應值為 None。
    """
    if cp not in ('C', 'P'):
        raise ValueError(f"cp 必須為 'C' 或 'P'，收到 {cp!r}")

    mid_price = (bid + ask) / 2.0
    return {
        "iv_mid":  calc_iv_newton(mid_price,  S, K, T, r, cp),
        "iv_bid":  calc_iv_newton(bid,        S, K, T, r, cp),
        "iv_ask":  calc_iv_newton(ask,        S, K, T, r, cp),
        "iv_last": calc_iv_newton(last_price, S, K, T, r, cp),
    }
