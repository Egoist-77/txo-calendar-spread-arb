# calendar_spread_arb/config.py
# ============================================================
# 策略全域參數設定檔
# 所有可調整的數值集中在此，方便切換模擬/實盤參數
# ============================================================

# --- 選擇權定價參數 ---
RISK_FREE_RATE: float = 0.02        # 無風險利率（年化 2%，台灣央行基準利率估計值）| 有效範圍 0.0~1.0

# --- 套利信號門檻 ---
FIXED_THRESHOLD: float = 0.04       # 固定 IV Spread 門檻（0.04 = 4%）| 有效範圍 0.0~1.0
ZSCORE_THRESHOLD: float = 2.0       # z-score 動態門檻（標準差倍數）| 有效範圍 0.0~5.0
ZSCORE_MIN_SAMPLES: int = 30        # 啟用 z-score 所需的最少歷史樣本數

# --- 報價新鮮度守衛 ---
STALE_MS: int = 500                 # 報價最大可接受延遲（毫秒）

# --- 記憶體暫存設定 ---
SPREAD_HISTORY_LEN: int = 200       # 每個 (strike, cp) 保存的 spread 歷史長度 | 必須 >= ZSCORE_MIN_SAMPLES

# --- 信號觸發模式 ---
SIGNAL_MODE: str = "AND"            # "OR"：固定門檻 OR z-score 任一觸發即產生信號
                                    # "AND"：兩者同時滿足才觸發（更嚴格）

# --- 到期月份（真實 / 模擬共用）---
NEAR_EXPIRY: str = "202606"         # 近月到期代碼（YYYYMM 格式）
FAR_EXPIRY: str = "202607"          # 遠月到期代碼

# --- 訂閱的履約價清單（真實 API 與模擬共用）---
# 以現貨 ~23670 為中心，200 點間距，涵蓋 ±1000 點
SIMULATED_STRIKES: list[int] = [22800, 23000, 23200, 23400, 23600, 23800, 24000, 24200, 24400]

# --- MockFeed 專用參數（接真實 API 時不使用）---
SIMULATED_SPOT: float = 23670.0     # 模擬台指現貨價（對應真實市場水準）
TICK_INTERVAL_MS: float = 50.0      # 模擬 Tick 產生間隔（毫秒）

# ============================================================
# 運行時設定一致性驗證
# ============================================================
assert SPREAD_HISTORY_LEN >= ZSCORE_MIN_SAMPLES, \
    f"SPREAD_HISTORY_LEN({SPREAD_HISTORY_LEN}) 必須 >= ZSCORE_MIN_SAMPLES({ZSCORE_MIN_SAMPLES})"
assert SIGNAL_MODE in ("OR", "AND"), \
    f"SIGNAL_MODE 必須為 'OR' 或 'AND'，目前值：{SIGNAL_MODE!r}"
