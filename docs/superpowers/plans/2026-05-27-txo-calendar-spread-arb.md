# 台指選擇權跨月份時間價差套利系統 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一套以事件驅動 Callback 架構運作的台指選擇權 Calendar Spread 套利框架，含高效 IV 反推、Freshness Guard 防鬼訊號、雙重門檻信號觸發，並預留真實下單區塊。

**Architecture:** 七個職責單一的模組，透過 `on_tick(tick)` callback 串接；IV 狀態以 dict+deque 儲存於記憶體；spread 偵測採固定門檻與 per-strike rolling z-score 雙重門檻。

**Tech Stack:** Python 3.11, numpy 2.4.3, pandas 3.0.1（已安裝）；scipy 僅作 brentq fallback（可選安裝）；無外部 API 依賴（模擬模式）。

---

## 檔案結構

```
calendar_spread_arb/
├── config.py             # 所有策略參數常數
├── iv_engine.py          # Black-Scholes 定價 + Newton-Raphson IV 反推
├── mock_feed.py          # 模擬 Shioaji Tick 產生器（含 subscribe/callback 介面）
├── iv_store.py           # 近/遠月 IV 狀態暫存器（dict + deque）
├── spread_detector.py    # IV Spread 偵測器（固定門檻 + z-score）
├── order_block.py        # 下單邏輯預留區塊
└── main.py               # 主程式：組裝模組並啟動

tests/
├── __init__.py
├── test_iv_engine.py     # BS 定價、vega、Newton-Raphson IV 反推單元測試
├── test_iv_store.py      # 狀態存取、freshness、spread history 單元測試
└── test_spread_detector.py  # 固定門檻、z-score、AND/OR 模式整合測試
```

---

## Task 1：建立專案骨架與 config.py

**Files:**
- Create: `calendar_spread_arb/config.py`
- Create: `calendar_spread_arb/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1.1：建立目錄結構**

```powershell
New-Item -ItemType Directory -Force "calendar_spread_arb"
New-Item -ItemType Directory -Force "tests"
New-Item -ItemType File -Force "calendar_spread_arb/__init__.py"
New-Item -ItemType File -Force "tests/__init__.py"
```

- [ ] **Step 1.2：撰寫 config.py**

建立 `calendar_spread_arb/config.py`：

```python
# calendar_spread_arb/config.py
# ============================================================
# 策略全域參數設定檔
# 所有可調整的數值集中在此，方便切換模擬/實盤參數
# ============================================================

# --- 選擇權定價參數 ---
RISK_FREE_RATE: float = 0.02        # 無風險利率（年化 2%，台灣央行基準利率估計值）

# --- 套利信號門檻 ---
FIXED_THRESHOLD: float = 0.02       # 固定 IV Spread 門檻（0.02 = 2%）
ZSCORE_THRESHOLD: float = 2.0       # z-score 動態門檻（標準差倍數）
ZSCORE_MIN_SAMPLES: int = 30        # 啟用 z-score 所需的最少歷史樣本數

# --- 報價新鮮度守衛 ---
STALE_MS: int = 500                 # 報價最大可接受延遲（毫秒）；
                                    # 近月與遠月報價都需在此視窗內更新才觸發計算

# --- 記憶體暫存設定 ---
SPREAD_HISTORY_LEN: int = 200       # 每個 (strike, cp) 保存的 spread 歷史長度
                                    # 用於 rolling z-score 計算

# --- 信號觸發模式 ---
SIGNAL_MODE: str = "OR"             # "OR"：固定門檻 OR z-score 任一觸發即產生信號
                                    # "AND"：兩者同時滿足才觸發（更嚴格，假信號更少）

# --- 模擬參數 ---
NEAR_EXPIRY: str = "202506"         # 近月到期代碼（YYYYMM 格式）
FAR_EXPIRY: str = "202507"          # 遠月到期代碼
SIMULATED_STRIKES: list = [16800, 16900, 17000, 17100, 17200]  # 模擬的履約價清單
SIMULATED_SPOT: float = 17000.0     # 模擬台指現貨價
TICK_INTERVAL_MS: float = 50.0      # 模擬 Tick 產生間隔（毫秒）
```

- [ ] **Step 1.3：安裝 pytest（若尚未安裝）**

```powershell
pip install pytest
```

預期輸出：`Successfully installed pytest-...` 或 `Requirement already satisfied`

---

## Task 2：iv_engine.py — Black-Scholes 定價引擎與 Newton-Raphson IV 反推

**Files:**
- Create: `calendar_spread_arb/iv_engine.py`
- Test: `tests/test_iv_engine.py`

- [ ] **Step 2.1：撰寫失敗測試**

建立 `tests/test_iv_engine.py`：

```python
# tests/test_iv_engine.py
# ============================================================
# IV 引擎單元測試
# 驗證 Black-Scholes 定價、vega 計算、Newton-Raphson IV 反推
# ============================================================
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from calendar_spread_arb.iv_engine import bs_price, bs_vega, calc_iv_newton


class TestBsPrice:
    """Black-Scholes 定價函式測試"""

    def test_call_atm_positive(self):
        """ATM Call 選擇權價格必須大於零"""
        price = bs_price(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02, cp='C')
        assert price > 0

    def test_put_atm_positive(self):
        """ATM Put 選擇權價格必須大於零"""
        price = bs_price(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02, cp='P')
        assert price > 0

    def test_put_call_parity(self):
        """Put-Call Parity 驗證：C - P = S - K*exp(-rT)"""
        import math
        S, K, T, r, sigma = 17000, 17000, 30/365, 0.02, 0.20
        call = bs_price(sigma, S, K, T, r, 'C')
        put  = bs_price(sigma, S, K, T, r, 'P')
        parity = S - K * math.exp(-r * T)
        assert abs((call - put) - parity) < 0.01, \
            f"Put-Call Parity 偏差過大：{abs((call - put) - parity):.4f}"

    def test_zero_time_call_intrinsic(self):
        """到期日時（T=0）Call 價格應等於內含價值"""
        price = bs_price(sigma=0.20, S=17100, K=17000, T=0, r=0.02, cp='C')
        assert abs(price - 100) < 0.01

    def test_known_value(self):
        """已知數值驗證：ATM Call 30天 20% vol 約 300-400 點"""
        price = bs_price(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02, cp='C')
        assert 250 < price < 500, f"ATM Call 價格 {price:.1f} 超出合理範圍"


class TestBsVega:
    """Vega 計算測試"""

    def test_vega_positive_atm(self):
        """ATM 選擇權的 vega 必須大於零"""
        vega = bs_vega(sigma=0.20, S=17000, K=17000, T=30/365, r=0.02)
        assert vega > 0

    def test_vega_zero_at_expiry(self):
        """到期日（T=0）時 vega 應為零"""
        vega = bs_vega(sigma=0.20, S=17000, K=17000, T=0, r=0.02)
        assert vega == 0.0


class TestCalcIvNewton:
    """Newton-Raphson IV 反推測試"""

    def test_roundtrip_call(self):
        """正向算出價格後，反推 IV 應還原原始 IV（誤差 < 0.1%）"""
        true_iv = 0.18
        S, K, T, r = 17000, 17000, 30/365, 0.02
        price = bs_price(true_iv, S, K, T, r, 'C')
        recovered_iv = calc_iv_newton(price, S, K, T, r, 'C')
        assert recovered_iv is not None
        assert abs(recovered_iv - true_iv) < 0.001, \
            f"IV 反推誤差 {abs(recovered_iv - true_iv):.4f} 超出容忍值"

    def test_roundtrip_put(self):
        """Put 選擇權 IV 反推正確性"""
        true_iv = 0.22
        S, K, T, r = 17000, 17200, 30/365, 0.02
        price = bs_price(true_iv, S, K, T, r, 'P')
        recovered_iv = calc_iv_newton(price, S, K, T, r, 'P')
        assert recovered_iv is not None
        assert abs(recovered_iv - true_iv) < 0.001

    def test_returns_none_for_zero_price(self):
        """深度 OTM 價格為 0 時，應回傳 None 而非崩潰"""
        result = calc_iv_newton(0.0, S=17000, K=20000, T=1/365, r=0.02, cp='C')
        assert result is None

    def test_high_vol_roundtrip(self):
        """高波動率（50%）情境下的 IV 反推"""
        true_iv = 0.50
        S, K, T, r = 17000, 17000, 60/365, 0.02
        price = bs_price(true_iv, S, K, T, r, 'C')
        recovered_iv = calc_iv_newton(price, S, K, T, r, 'C')
        assert recovered_iv is not None
        assert abs(recovered_iv - true_iv) < 0.001
```

- [ ] **Step 2.2：執行測試確認失敗**

```powershell
python -m pytest tests/test_iv_engine.py -v
```

預期：`ImportError: cannot import name 'bs_price' from 'calendar_spread_arb.iv_engine'`（或 ModuleNotFoundError）

- [ ] **Step 2.3：撰寫 iv_engine.py 實作**

建立 `calendar_spread_arb/iv_engine.py`：

```python
# calendar_spread_arb/iv_engine.py
# ============================================================
# Black-Scholes 選擇權定價引擎
#
# 設計原則：
#   1. 核心計算使用純 math 模組，不依賴 scipy（低延遲）
#   2. Newton-Raphson 反推 IV：利用 vega 作為梯度，3-5 次收斂
#   3. 失敗時 fallback 到 scipy.optimize.brentq（可靠性保底）
#   4. 對外輸出 iv_mid / iv_bid / iv_ask 三個 IV 值
# ============================================================

import math
from typing import Optional

# ---- 常數 ----
_SQRT_2PI = math.sqrt(2 * math.pi)
_SQRT2    = math.sqrt(2)


# ============================================================
# 內部輔助：標準常態分布 CDF 與 PDF
# 使用 math.erf 取代 scipy.stats.norm，速度更快
# ============================================================

def _norm_cdf(x: float) -> float:
    """標準常態分布累積分布函數（CDF）"""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _norm_pdf(x: float) -> float:
    """標準常態分布概率密度函數（PDF）"""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


# ============================================================
# Black-Scholes 定價函式
# ============================================================

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
    # 邊界條件：到期或零波動率時回傳內含價值
    if T <= 0 or sigma <= 0:
        if cp == 'C':
            return max(0.0, S - K)
        else:
            return max(0.0, K - S)

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

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * _norm_pdf(d1) * math.sqrt(T)


# ============================================================
# Newton-Raphson 隱含波動率（IV）反推
# ============================================================

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

    典型收斂速度：3~5 次迭代（遠快於 brentq 的 50+ 次函數求值）

    Args:
        option_price  : 市場觀察到的選擇權價格
        S, K, T, r, cp: 同 bs_price 參數說明
        initial_sigma : 初始猜測波動率（預設 30%）
        max_iter      : 最大迭代次數
        tol           : 收斂容忍誤差

    Returns:
        反推出的 IV（0 到 10 之間）；失敗時回傳 None
    """
    # 排除無效輸入
    if option_price <= 0 or T <= 0:
        return None

    # 最低有效期權價格（深 OTM 或極小值）
    intrinsic = max(0.0, (S - K) if cp == 'C' else (K - S))
    if option_price < intrinsic - 0.5:
        return None

    sigma = initial_sigma

    for i in range(max_iter):
        price_bs = bs_price(sigma, S, K, T, r, cp)
        vega_bs  = bs_vega(sigma, S, K, T, r)

        # Vega 太小：接近到期或極深 OTM，牛頓法不穩定 → 改用 fallback
        if abs(vega_bs) < 1e-10:
            break

        diff = option_price - price_bs

        # 達到收斂精度
        if abs(diff) < tol:
            return sigma

        # 牛頓步進
        sigma = sigma + diff / vega_bs

        # 限制在合理 IV 範圍（0.01% ~ 1000%）
        sigma = max(1e-4, min(sigma, 10.0))

    # ---- Fallback：brentq 二分法（可靠但較慢）----
    return _brentq_fallback(option_price, S, K, T, r, cp)


def _brentq_fallback(
    option_price: float, S: float, K: float,
    T: float, r: float, cp: str
) -> Optional[float]:
    """
    scipy.optimize.brentq 作為 Newton-Raphson 失敗時的保底方案。
    若 scipy 未安裝則直接回傳 None。
    """
    try:
        from scipy.optimize import brentq
        objective = lambda s: bs_price(s, S, K, T, r, cp) - option_price
        # 確認區間端點異號（brentq 要求）
        lo, hi = 1e-4, 10.0
        if objective(lo) * objective(hi) > 0:
            return None
        return brentq(objective, lo, hi, xtol=1e-6, maxiter=200)
    except ImportError:
        # scipy 未安裝：靜默失敗，回傳 None
        return None
    except Exception:
        return None


# ============================================================
# 對外主要介面：計算三個 IV 版本
# ============================================================

def calc_all_ivs(
    S: float, K: float, T: float, r: float, cp: str,
    last_price: float, bid: float, ask: float
) -> dict:
    """
    計算選擇權的三種 IV 版本：

    - iv_mid : 以 (bid+ask)/2 計算，理論參考值
    - iv_bid : 以 bid 計算（賣出時收到的價格對應 IV）
    - iv_ask : 以 ask 計算（買進時付出的價格對應 IV）

    套利信號判斷應使用 iv_bid / iv_ask（可執行 IV），
    不應使用 iv_mid（未必可成交）

    Returns:
        dict with keys: iv_mid, iv_bid, iv_ask, iv_last
        任一值無法計算時為 None
    """
    mid_price = (bid + ask) / 2.0
    return {
        "iv_mid":  calc_iv_newton(mid_price, S, K, T, r, cp),
        "iv_bid":  calc_iv_newton(bid,       S, K, T, r, cp),
        "iv_ask":  calc_iv_newton(ask,       S, K, T, r, cp),
        "iv_last": calc_iv_newton(last_price, S, K, T, r, cp),
    }
```

- [ ] **Step 2.4：執行測試確認通過**

```powershell
python -m pytest tests/test_iv_engine.py -v
```

預期輸出：
```
tests/test_iv_engine.py::TestBsPrice::test_call_atm_positive PASSED
tests/test_iv_engine.py::TestBsPrice::test_put_atm_positive PASSED
tests/test_iv_engine.py::TestBsPrice::test_put_call_parity PASSED
tests/test_iv_engine.py::TestBsPrice::test_zero_time_call_intrinsic PASSED
tests/test_iv_engine.py::TestBsPrice::test_known_value PASSED
tests/test_iv_engine.py::TestBsVega::test_vega_positive_atm PASSED
tests/test_iv_engine.py::TestBsVega::test_vega_zero_at_expiry PASSED
tests/test_iv_engine.py::TestCalcIvNewton::test_roundtrip_call PASSED
tests/test_iv_engine.py::TestCalcIvNewton::test_roundtrip_put PASSED
tests/test_iv_engine.py::TestCalcIvNewton::test_returns_none_for_zero_price PASSED
tests/test_iv_engine.py::TestCalcIvNewton::test_high_vol_roundtrip PASSED
11 passed in X.XXs
```

---

## Task 3：mock_feed.py — 模擬 Shioaji Tick 產生器

**Files:**
- Create: `calendar_spread_arb/mock_feed.py`

- [ ] **Step 3.1：撰寫 mock_feed.py**

建立 `calendar_spread_arb/mock_feed.py`：

```python
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
from typing import Callable, List

from calendar_spread_arb import config


# ============================================================
# Tick 資料結構（模擬 Shioaji 的 TickFOPv1）
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
        self._spot = spot_price or config.SIMULATED_SPOT
        self._callbacks: List[Callable[[TickData], None]] = []
        self._running = False
        self._thread: threading.Thread = None

        # 為每個合約維護一個緩慢漂移的 IV 基準（模擬真實市場）
        # key: (expiry_month, strike, cp)
        self._iv_base = self._init_iv_base()

    def _init_iv_base(self) -> dict:
        """初始化每個合約的基準 IV（模擬 vol smile 結構）"""
        iv_base = {}
        for expiry in [config.NEAR_EXPIRY, config.FAR_EXPIRY]:
            for strike in config.SIMULATED_STRIKES:
                for cp in ['C', 'P']:
                    # 模擬微笑曲線：ATM IV 最低，OTM 較高
                    otm_ratio = abs(strike - self._spot) / self._spot
                    smile_premium = otm_ratio * 0.5      # OTM 溢價
                    # 遠月 IV 通常略高於近月（time spread 的核心）
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
        self._callbacks.append(callback)

    def start(self) -> None:
        """啟動背景執行緒，開始產生模擬 Tick（非阻塞）"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._generate_loop,
            daemon=True,
            name="MockFeedThread"
        )
        self._thread.start()

    def stop(self) -> None:
        """停止 Tick 產生"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

    # ---- 內部實作 ----

    def _generate_loop(self) -> None:
        """
        主迴圈：交替為近月/遠月的各個合約產生 Tick。
        加入隨機延遲以模擬真實市場的不規則到達。
        """
        interval_s = config.TICK_INTERVAL_MS / 1000.0

        while self._running:
            # 隨機漫步更新標的現貨價（模擬指數波動）
            self._spot *= math.exp(random.gauss(0, 0.0001))

            # 依序為所有合約產生 Tick（近月先、遠月後，模擬真實報價序列）
            for expiry in [config.NEAR_EXPIRY, config.FAR_EXPIRY]:
                for strike in config.SIMULATED_STRIKES:
                    for cp in ['C', 'P']:
                        if not self._running:
                            return
                        tick = self._make_tick(expiry, float(strike), cp)
                        for cb in self._callbacks:
                            try:
                                cb(tick)
                            except Exception as e:
                                print(f"[MockFeed] callback 發生錯誤：{e}")

            time.sleep(interval_s)

    def _make_tick(self, expiry: str, strike: float, cp: str) -> TickData:
        """
        為指定合約產生一筆模擬 Tick

        定價邏輯：
          1. 從基準 IV 加入小幅隨機漂移（模擬 IV 波動）
          2. 用 BS 公式計算理論 mid price
          3. 加入隨機 bid-ask spread（模擬流動性）
        """
        from calendar_spread_arb.iv_engine import bs_price

        key = (expiry, strike, cp)

        # IV 隨機漂移（布朗運動型）
        self._iv_base[key] += random.gauss(0, 0.001)
        self._iv_base[key] = max(0.05, min(self._iv_base[key], 2.0))

        sigma = self._iv_base[key]
        S = self._spot

        # 計算到期時間（近月約 30 天，遠月約 60 天）
        T = 30 / 365 if expiry == config.NEAR_EXPIRY else 60 / 365

        # 計算 mid price
        mid = bs_price(sigma, S, strike, T, config.RISK_FREE_RATE, cp)
        mid = max(mid, 1.0)  # 最低 1 點（避免零價格）

        # 模擬 bid-ask spread（流動性差時較寬）
        # TXO 真實 spread 約 5~30 點
        raw_spread = max(5.0, mid * 0.02)   # 至少 5 點，或 2% 的 mid price
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
            timestamp=datetime.now(timezone.utc)
        )
```

---

## Task 4：iv_store.py — IV 狀態暫存器

**Files:**
- Create: `calendar_spread_arb/iv_store.py`
- Test: `tests/test_iv_store.py`

- [ ] **Step 4.1：撰寫失敗測試**

建立 `tests/test_iv_store.py`：

```python
# tests/test_iv_store.py
import pytest
import sys, os, time
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from calendar_spread_arb.iv_store import IVStore


class TestIVStoreBasic:
    """基本存取測試"""

    def test_update_and_get(self):
        """存入後應能正確取出"""
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
        """不存在的 key 應回傳 None"""
        store = IVStore()
        assert store.get("202506", 99999, "C") is None

    def test_update_overwrites(self):
        """重複更新同一 key 應覆蓋舊值"""
        store = IVStore()
        now = datetime.now(timezone.utc)
        store.update("202506", 17000, "C", 0.20, 0.19, 0.21, now)
        store.update("202506", 17000, "C", 0.25, 0.24, 0.26, now)
        rec = store.get("202506", 17000, "C")
        assert abs(rec["iv_mid"] - 0.25) < 1e-9


class TestFreshnessGuard:
    """報價新鮮度守衛測試"""

    def test_fresh_quotes_both_recent(self):
        """兩個報價都在視窗內 → is_pair_fresh 應回傳 True"""
        store = IVStore()
        now = datetime.now(timezone.utc)
        store.update("202506", 17000, "C", 0.20, 0.19, 0.21, now)
        store.update("202507", 17000, "C", 0.22, 0.21, 0.23, now)
        assert store.is_pair_fresh("202506", "202507", 17000, "C", stale_ms=500)

    def test_stale_near_month(self):
        """近月報價過期（超過 stale_ms）→ 應回傳 False"""
        store = IVStore()
        old_ts = datetime.now(timezone.utc) - timedelta(seconds=2)
        now    = datetime.now(timezone.utc)
        store.update("202506", 17000, "C", 0.20, 0.19, 0.21, old_ts)  # 過期
        store.update("202507", 17000, "C", 0.22, 0.21, 0.23, now)
        assert not store.is_pair_fresh("202506", "202507", 17000, "C", stale_ms=500)


class TestSpreadHistory:
    """Spread 歷史與 z-score 測試"""

    def test_zscore_none_before_min_samples(self):
        """樣本不足 30 時，z-score 應回傳 None"""
        store = IVStore()
        for i in range(10):
            store.push_spread(17000, "C", 0.02 + i * 0.001)
        assert store.calc_zscore(17000, "C", 0.03) is None

    def test_zscore_valid_after_min_samples(self):
        """累積足夠樣本後，z-score 應為有效數值"""
        store = IVStore()
        for i in range(50):
            store.push_spread(17000, "C", 0.02)  # 固定值，製造穩定分布
        store.push_spread(17000, "C", 0.02)
        z = store.calc_zscore(17000, "C", 0.02)
        # 均值附近，z-score 應接近 0
        assert z is not None
        assert abs(z) < 1.0

    def test_zscore_detects_outlier(self):
        """異常值的 z-score 應顯著大於門檻"""
        store = IVStore()
        for _ in range(50):
            store.push_spread(17000, "C", 0.02)  # 穩定基準
        # 推入異常值（比均值高出許多標準差）
        z = store.calc_zscore(17000, "C", 0.20)
        assert z is not None
        assert z > 2.0
```

- [ ] **Step 4.2：執行測試確認失敗**

```powershell
python -m pytest tests/test_iv_store.py -v
```

預期：`ImportError` 或 `ModuleNotFoundError`

- [ ] **Step 4.3：撰寫 iv_store.py 實作**

建立 `calendar_spread_arb/iv_store.py`：

```python
# calendar_spread_arb/iv_store.py
# ============================================================
# IV 狀態暫存器
#
# 職責：
#   1. 以 dict 維護每個合約的最新 IV（iv_mid / iv_bid / iv_ask）
#   2. 記錄每次更新的時間戳（供 Freshness Guard 使用）
#   3. 以 deque 維護每個 (strike, cp) 的 IV Spread 歷史
#      （用於 rolling z-score 計算）
#
# 記憶體使用估算（100 個合約 × 200 筆歷史）：
#   ~100 × (3 float + 1 datetime + 1 deque×200 float)
#   ≈ 幾百 KB，遠低於毫秒級延遲需求
# ============================================================

import numpy as np
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from calendar_spread_arb import config


class IVStore:
    """
    近/遠月選擇權 IV 的記憶體暫存器

    兩層字典結構：
      _iv_data[(expiry_month, strike, cp)]
          → { iv_mid, iv_bid, iv_ask, last_ts }

      _spread_history[(strike, cp)]
          → deque(maxlen=SPREAD_HISTORY_LEN)  # 用於 z-score
    """

    def __init__(self):
        # 合約 IV 資料：key = (expiry_month, strike, cp)
        self._iv_data: Dict[tuple, Dict[str, Any]] = {}

        # Spread 歷史：key = (strike, cp)，值為 IV spread 的 deque
        self._spread_history: Dict[tuple, deque] = {}

    # ----------------------------------------------------------
    # IV 存取
    # ----------------------------------------------------------

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

    # ----------------------------------------------------------
    # Freshness Guard
    # ----------------------------------------------------------

    def is_pair_fresh(
        self,
        near_expiry: str,
        far_expiry: str,
        strike: float,
        cp: str,
        stale_ms: int = None
    ) -> bool:
        """
        檢查近月與遠月報價是否都在新鮮度視窗內

        防止「鬼訊號」：若其中一方報價已過期，
        用新舊報價混合計算的 IV spread 是虛假的。

        Args:
            stale_ms: 最大可接受延遲（毫秒）；None 時使用 config.STALE_MS

        Returns:
            True = 兩方報價都新鮮，可以安全計算 spread
            False = 至少一方過期，跳過本次計算
        """
        if stale_ms is None:
            stale_ms = config.STALE_MS

        near_rec = self.get(near_expiry, strike, cp)
        far_rec  = self.get(far_expiry,  strike, cp)

        if near_rec is None or far_rec is None:
            return False

        now = datetime.now(timezone.utc)
        cutoff = timedelta(milliseconds=stale_ms)

        near_age = now - near_rec["last_ts"]
        far_age  = now - far_rec["last_ts"]

        return near_age < cutoff and far_age < cutoff

    # ----------------------------------------------------------
    # Spread 歷史管理（供 z-score 使用）
    # ----------------------------------------------------------

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

        注意：z-score 只在同一 (strike, cp) 的歷史內計算，
        不跨履約價比較，以避免 vol smile 結構干擾基準線。

        Args:
            spread_now: 本次計算出的 IV spread

        Returns:
            z-score；樣本不足（< ZSCORE_MIN_SAMPLES）時回傳 None
        """
        key = (float(strike), cp)
        history = self._spread_history.get(key)

        if history is None or len(history) < config.ZSCORE_MIN_SAMPLES:
            return None  # 樣本不足，不輸出信號

        arr = np.array(history, dtype=np.float64)
        mu    = arr.mean()
        sigma = arr.std()

        if sigma < 1e-9:
            return None  # 標準差為零：歷史值全相同，無意義

        return float((spread_now - mu) / sigma)
```

- [ ] **Step 4.4：執行測試確認通過**

```powershell
python -m pytest tests/test_iv_store.py -v
```

預期：所有 8 個測試通過

---

## Task 5：spread_detector.py — IV Spread 信號偵測器

**Files:**
- Create: `calendar_spread_arb/spread_detector.py`
- Test: `tests/test_spread_detector.py`

- [ ] **Step 5.1：撰寫失敗測試**

建立 `tests/test_spread_detector.py`：

```python
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
    old = now - timedelta(seconds=2)  # 過期時間戳

    near_ts = now if near_fresh else old
    far_ts  = now if far_fresh  else old

    mid_near = (near_bid + near_ask) / 2
    mid_far  = (far_bid  + far_ask)  / 2

    store.update(config.NEAR_EXPIRY, 17000, "C",
                 iv_mid=mid_near, iv_bid=near_bid, iv_ask=near_ask, ts=near_ts)
    store.update(config.FAR_EXPIRY,  17000, "C",
                 iv_mid=mid_far,  iv_bid=far_bid,  iv_ask=far_ask,  ts=far_ts)

    # 填充 spread 歷史（供 z-score 測試）
    for _ in range(history_count):
        store.push_spread(17000, "C", history_spread)

    return store


class TestFreshnessGuardInDetector:
    """Freshness Guard 整合測試"""

    def test_stale_quote_returns_no_signal(self):
        """報價過期時，detect_signal 應回傳 None"""
        store = _make_store_with_ivs(
            near_bid=0.18, near_ask=0.20,
            far_bid=0.21,  far_ask=0.23,
            near_fresh=False  # 近月報價過期
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is None


class TestFixedThreshold:
    """固定門檻觸發測試"""

    def test_fixed_threshold_triggered(self):
        """可執行 spread > FIXED_THRESHOLD 時應觸發信號"""
        # far_bid=0.25 - near_ask=0.20 = 0.05 > 0.02 (FIXED_THRESHOLD)
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.25,  far_ask=0.27
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is not None
        assert result["fixed_triggered"] is True

    def test_fixed_threshold_not_triggered(self):
        """spread 太小時不應觸發"""
        # far_bid=0.205 - near_ask=0.20 = 0.005 < 0.02
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.205, far_ask=0.215
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        # 固定門檻不觸發（z-score 樣本也不足）→ None
        assert result is None or result["fixed_triggered"] is False


class TestZScoreThreshold:
    """Z-score 動態門檻觸發測試"""

    def test_zscore_not_triggered_without_history(self):
        """歷史不足時，z-score 不觸發"""
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.205, far_ask=0.215,
            history_count=10  # 不足 30
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is None or result.get("zscore_triggered") is False

    def test_zscore_triggered_with_outlier(self):
        """歷史穩定時，異常 spread 應觸發 z-score 信號"""
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.45,  far_ask=0.47,  # 遠月 IV 大幅高於近月
            history_count=50,
            history_spread=0.005  # 歷史 spread 很小（基準低）
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is not None
        assert result["zscore_triggered"] is True


class TestSignalContent:
    """信號內容正確性測試"""

    def test_signal_contains_required_fields(self):
        """觸發的信號必須包含所有必要欄位"""
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

    def test_direction_buy_far_sell_near(self):
        """遠月 IV 顯著高於近月 → 方向應為 BUY_NEAR_SELL_FAR"""
        # 買近月 ask=0.20，賣遠月 bid=0.25 → spread = 0.05（正值）
        store = _make_store_with_ivs(
            near_bid=0.19, near_ask=0.20,
            far_bid=0.25,  far_ask=0.27
        )
        result = detect_signal(store, config.NEAR_EXPIRY, config.FAR_EXPIRY, 17000, "C")
        assert result is not None
        assert result["direction"] == "BUY_NEAR_SELL_FAR"
```

- [ ] **Step 5.2：執行測試確認失敗**

```powershell
python -m pytest tests/test_spread_detector.py -v
```

預期：`ImportError`（`spread_detector` 尚未建立）

- [ ] **Step 5.3：撰寫 spread_detector.py 實作**

建立 `calendar_spread_arb/spread_detector.py`：

```python
# calendar_spread_arb/spread_detector.py
# ============================================================
# IV Spread 信號偵測器
#
# 職責：
#   對每個 (strike, cp) 組合：
#   1. 通過 Freshness Guard（防鬼訊號）
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
    對指定 (strike, cp) 組合執行 IV Spread 套利信號偵測

    Args:
        store       : IVStore 實例（含最新 IV 資料與歷史）
        near_expiry : 近月代碼，例如 "202506"
        far_expiry  : 遠月代碼，例如 "202507"
        strike      : 履約價
        cp          : 'C' 或 'P'

    Returns:
        觸發時：dict 含信號明細（見下方說明）
        未觸發：None
    """

    # ==== 步驟 1：Freshness Guard ====
    # 防止用「新近月」對比「舊遠月」產生鬼訊號
    if not store.is_pair_fresh(near_expiry, far_expiry, strike, cp):
        return None

    near = store.get(near_expiry, strike, cp)
    far  = store.get(far_expiry,  strike, cp)

    # 任一方向缺少可執行 IV 則跳過
    if near is None or far is None:
        return None
    if None in (near["iv_bid"], near["iv_ask"], far["iv_bid"], far["iv_ask"]):
        return None

    # ==== 步驟 2：計算可執行 IV Spread ====
    #
    # 方向A：買近月（付 near_ask）+ 賣遠月（收 far_bid）
    #   → 正值代表「遠月 IV 溢價」，值越大套利空間越大
    spread_buy_near = far["iv_bid"] - near["iv_ask"]

    # 方向B：買遠月（付 far_ask）+ 賣近月（收 near_bid）
    #   → 正值代表「近月 IV 溢價」（反向價差）
    spread_buy_far  = near["iv_bid"] - far["iv_ask"]

    # 選擇利潤較大的方向
    if spread_buy_near >= spread_buy_far:
        executable_spread = spread_buy_near
        direction = "BUY_NEAR_SELL_FAR"
    else:
        executable_spread = spread_buy_far
        direction = "BUY_FAR_SELL_NEAR"

    # 記錄到歷史（用於 z-score 的 rolling window）
    store.push_spread(strike, cp, executable_spread)

    # ==== 步驟 3：固定門檻檢查 ====
    fixed_triggered = abs(executable_spread) > config.FIXED_THRESHOLD

    # ==== 步驟 4：動態 z-score 門檻（per-strike history）====
    zscore = store.calc_zscore(strike, cp, executable_spread)
    zscore_triggered = (
        zscore is not None and abs(zscore) > config.ZSCORE_THRESHOLD
    )

    # ==== 步驟 5：組合觸發條件 ====
    if config.SIGNAL_MODE == "AND":
        triggered = fixed_triggered and zscore_triggered
    else:  # "OR"（預設）
        triggered = fixed_triggered or zscore_triggered

    if not triggered:
        return None

    # ==== 回傳信號明細 ====
    return {
        "strike":            float(strike),
        "cp":                cp,
        "near_expiry":       near_expiry,
        "far_expiry":        far_expiry,
        "direction":         direction,          # BUY_NEAR_SELL_FAR 或 BUY_FAR_SELL_NEAR
        "executable_spread": executable_spread,  # 可執行 IV Spread（用 bid/ask 計算）
        "mid_spread":        far["iv_mid"] - near["iv_mid"]  if (far["iv_mid"] and near["iv_mid"]) else None,
        "zscore":            zscore,             # None = 樣本不足
        "fixed_triggered":   fixed_triggered,
        "zscore_triggered":  zscore_triggered,
        "near_iv_bid":       near["iv_bid"],
        "near_iv_ask":       near["iv_ask"],
        "far_iv_bid":        far["iv_bid"],
        "far_iv_ask":        far["iv_ask"],
    }
```

- [ ] **Step 5.4：執行測試確認通過**

```powershell
python -m pytest tests/test_spread_detector.py -v
```

預期：所有測試通過

---

## Task 6：order_block.py — 下單邏輯預留區塊

**Files:**
- Create: `calendar_spread_arb/order_block.py`

- [ ] **Step 6.1：撰寫 order_block.py**

建立 `calendar_spread_arb/order_block.py`：

```python
# calendar_spread_arb/order_block.py
# ============================================================
# 套利信號下單邏輯預留區塊
#
# 目前：僅將信號格式化後印到控制台
# 日後：替換 TODO 區塊以接入真實 Shioaji 下單 API
# ============================================================

from typing import Dict, Any
from datetime import datetime, timezone


def on_signal(signal: Dict[str, Any]) -> None:
    """
    接收套利信號並執行對應動作。

    Args:
        signal: spread_detector.detect_signal() 回傳的信號字典，
                含 strike / cp / direction / executable_spread 等欄位

    實盤替換指引：
        將下方 TODO 區塊替換為 Shioaji API 呼叫，例如：
            api.place_order(contract_near, order_near)
            api.place_order(contract_far,  order_far)
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    direction_desc = {
        "BUY_NEAR_SELL_FAR": "買近月 + 賣遠月",
        "BUY_FAR_SELL_NEAR": "買遠月 + 賣近月",
    }.get(signal["direction"], signal["direction"])

    zscore_str = f"{signal['zscore']:.2f}" if signal["zscore"] is not None else "N/A（樣本不足）"

    trigger_flags = []
    if signal["fixed_triggered"]:
        trigger_flags.append(f"固定門檻(>{signal['executable_spread']:.4f})")
    if signal["zscore_triggered"]:
        trigger_flags.append(f"z-score({zscore_str}σ)")
    trigger_str = " + ".join(trigger_flags) if trigger_flags else "未知"

    print(
        f"\n{'='*60}\n"
        f"[{now_str}] 🚨 套利信號觸發\n"
        f"  商品    : TXO {signal['cp']} {int(signal['strike'])}\n"
        f"  方向    : {direction_desc}\n"
        f"  近月    : {signal['near_expiry']}  bid IV={signal['near_iv_bid']:.4f}  ask IV={signal['near_iv_ask']:.4f}\n"
        f"  遠月    : {signal['far_expiry']}   bid IV={signal['far_iv_bid']:.4f}  ask IV={signal['far_iv_ask']:.4f}\n"
        f"  可執行IV差: {signal['executable_spread']:+.4f} ({signal['executable_spread']*100:+.2f}%)\n"
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
    # from shioaji.constant import Action, FuturesOrderType, TFTOrderType
    #
    # if signal["direction"] == "BUY_NEAR_SELL_FAR":
    #     # 買進近月合約
    #     order_near = api.Order(
    #         price=near_ask_price,
    #         quantity=1,
    #         action=Action.Buy,
    #         price_type=TFTOrderType.LMT,
    #         order_type=OrderType.ROD,
    #     )
    #     # 賣出遠月合約
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
```

---

## Task 7：main.py — 主程式組裝

**Files:**
- Create: `calendar_spread_arb/main.py`

- [ ] **Step 7.1：撰寫 main.py**

建立 `calendar_spread_arb/main.py`：

```python
# calendar_spread_arb/main.py
# ============================================================
# 主程式入口：組裝所有模組並啟動事件驅動的套利監控
#
# 執行方式：
#   python -m calendar_spread_arb.main
#   或
#   python calendar_spread_arb/main.py
#
# Ctrl+C 優雅停止
# ============================================================

import time
import signal as _signal
from datetime import datetime, timezone

from calendar_spread_arb import config
from calendar_spread_arb.mock_feed import MockFeed, TickData
from calendar_spread_arb.iv_engine import calc_all_ivs
from calendar_spread_arb.iv_store import IVStore
from calendar_spread_arb.spread_detector import detect_signal
from calendar_spread_arb.order_block import on_signal

# ---- 全域狀態 ----
_store = IVStore()       # IV 暫存器（記憶體內）
_tick_count = 0          # 已處理 Tick 計數（用於控制台進度顯示）
_last_display_time = 0   # 上次狀態顯示時間


def on_tick(tick: TickData) -> None:
    """
    核心 Callback：每次收到新的 Tick 報價時被呼叫

    流程：
      1. 計算三種 IV（iv_mid / iv_bid / iv_ask）
      2. 更新 IVStore
      3. 偵測所有 (strike, cp) 組合的 IV Spread 信號
      4. 有信號時呼叫 on_signal 下單（目前為 log 輸出）
    """
    global _tick_count, _last_display_time

    # ---- 計算到期時間（年化）----
    T = 30 / 365 if tick.expiry_month == config.NEAR_EXPIRY else 60 / 365

    # ---- 反推三種 IV ----
    ivs = calc_all_ivs(
        S=config.SIMULATED_SPOT,    # 真實環境：改為即時台指現貨價
        K=tick.strike,
        T=T,
        r=config.RISK_FREE_RATE,
        cp=tick.cp,
        last_price=tick.last_price,
        bid=tick.bid,
        ask=tick.ask,
    )

    # ---- 更新 IVStore ----
    _store.update(
        expiry_month=tick.expiry_month,
        strike=tick.strike,
        cp=tick.cp,
        iv_mid=ivs["iv_mid"],
        iv_bid=ivs["iv_bid"],
        iv_ask=ivs["iv_ask"],
        ts=tick.timestamp,
    )

    # ---- 偵測套利信號（對每個 strike 與 CP 方向）----
    signal = detect_signal(
        store=_store,
        near_expiry=config.NEAR_EXPIRY,
        far_expiry=config.FAR_EXPIRY,
        strike=tick.strike,
        cp=tick.cp,
    )

    if signal is not None:
        on_signal(signal)

    # ---- 定時顯示運行狀態（每 5 秒）----
    _tick_count += 1
    now = time.time()
    if now - _last_display_time >= 5.0:
        _last_display_time = now
        ts_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(
            f"[{ts_str}] 運行中... "
            f"已處理 {_tick_count} 筆 Tick  |  "
            f"IVStore 合約數：{len(_store._iv_data)}  |  "
            f"最新 Tick：{tick.symbol}  "
            f"bid={tick.bid:.0f} ask={tick.ask:.0f} "
            f"iv_mid={ivs['iv_mid']:.4f}" if ivs['iv_mid'] else ""
        )


def main():
    print("=" * 60)
    print("台指選擇權 Calendar Spread 套利監控系統")
    print(f"  近月：{config.NEAR_EXPIRY}  遠月：{config.FAR_EXPIRY}")
    print(f"  固定門檻：{config.FIXED_THRESHOLD:.2%}  z-score 門檻：{config.ZSCORE_THRESHOLD}")
    print(f"  信號模式：{config.SIGNAL_MODE}")
    print(f"  報價新鮮度視窗：{config.STALE_MS}ms")
    print("=" * 60)
    print("按 Ctrl+C 停止\n")

    # 建立模擬行情產生器
    feed = MockFeed(spot_price=config.SIMULATED_SPOT)
    feed.subscribe(on_tick)

    # 優雅停止（捕捉 Ctrl+C）
    def handle_stop(sig, frame):
        print(f"\n\n[停止] 共處理 {_tick_count} 筆 Tick，程式結束。")
        feed.stop()
        raise SystemExit(0)

    _signal.signal(_signal.SIGINT, handle_stop)

    # 啟動行情（非阻塞）
    feed.start()

    # 主執行緒保持存活
    try:
        while True:
            time.sleep(1)
    except SystemExit:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 7.2：執行全部測試確認綠燈**

```powershell
python -m pytest tests/ -v
```

預期：所有測試通過（綠燈）

- [ ] **Step 7.3：啟動主程式驗證端到端運行**

```powershell
cd C:\Users\wu177
python -m calendar_spread_arb.main
```

預期輸出（每 5 秒一行狀態，有信號時額外輸出信號區塊）：
```
============================================================
台指選擇權 Calendar Spread 套利監控系統
  近月：202506  遠月：202507
  固定門檻：2.00%  z-score 門檻：2.0
  信號模式：OR
  報價新鮮度視窗：500ms
============================================================
按 Ctrl+C 停止

[12:34:56] 運行中... 已處理 240 筆 Tick  |  IVStore 合約數：20  |  ...

============================================================
[2026-05-27 12:35:02.123] 🚨 套利信號觸發
  商品    : TXO C 17000
  方向    : 買近月 + 賣遠月
  ...
============================================================
```

---

## 自審結果（Self-Review）

### Spec Coverage Check
| 規格需求 | 對應 Task |
|---------|---------|
| 模擬 Shioaji Tick 報價（symbol/成交/bid/ask） | Task 3 mock_feed.py |
| Black-Scholes IV 反推（scipy/scipy fallback） | Task 2 iv_engine.py |
| 近月/遠月 IV Spread 比較 | Task 5 spread_detector.py |
| 記憶體內計算（dict/deque） | Task 4 iv_store.py |
| Freshness Guard 防鬼訊號 | Task 4+5 |
| Per-Strike Z-Score（微笑隔離）| Task 4+5 |
| Newton-Raphson 高效 IV 反推 | Task 2 |
| Executable IV（bid/ask 分開）| Task 2+5 |
| 下單邏輯預留區塊 | Task 6 |

### Placeholder Scan
- ✅ 無 TBD / TODO 未填項目（下單區塊已明確標示並加入程式碼範例）
- ✅ 所有測試均包含完整 assert
- ✅ 無「Similar to Task N」類模糊引用

### Type Consistency
- `IVStore.update()` 在 Task 4 定義：`(expiry_month, strike, cp, iv_mid, iv_bid, iv_ask, ts)` → Task 7 main.py 呼叫一致 ✅
- `detect_signal()` 在 Task 5 定義：`(store, near_expiry, far_expiry, strike, cp)` → Task 7 呼叫一致 ✅
- `TickData` 在 Task 3 定義：`symbol / expiry_month / strike / cp / last_price / bid / ask / timestamp` → Task 7 使用一致 ✅
- `calc_all_ivs()` 在 Task 2 定義：`(S, K, T, r, cp, last_price, bid, ask)` → Task 7 呼叫一致 ✅
