# 台指選擇權跨月份時間價差套利系統 — 設計規格

**日期**：2026-05-27  
**作者**：量化交易工程師  
**狀態**：已確認，待實作

---

## 1. 專案目標

建立一套以 Python 為主的台指選擇權（TXO）跨月份時間價差套利（Calendar Spread Arbitrage）框架，具備以下能力：

- 模擬接收 Shioaji API 即時 Tick 報價（含 bid/ask/timestamp）
- 以 Newton-Raphson 高效反推隱含波動率（IV），輸出 iv_mid / iv_bid / iv_ask
- 同時追蹤近月與遠月相同履約價的 IV，計算可執行 IV Spread
- 採雙重門檻（固定值 + 動態 z-score）觸發套利信號
- 預留真實下單邏輯區塊，日後可直接接入 Shioaji 帳號

---

## 2. 執行環境

| 項目 | 版本 |
|------|------|
| Python | 3.11 |
| shioaji | 1.3.2（已安裝） |
| numpy | 2.4.3（已安裝） |
| pandas | 3.0.1（已安裝） |
| scipy | 待安裝（僅作 fallback） |
| 作業系統 | Windows 11 |

---

## 3. 架構總覽

```
calendar_spread_arb/
├── config.py             # 策略參數（利率、門檻、商品代碼、staleness window）
├── mock_feed.py          # 模擬 Shioaji Tick 產生器（仿 subscribe/on_tick callback）
├── iv_engine.py          # Black-Scholes + Newton-Raphson IV 反推引擎
├── iv_store.py           # 近/遠月 IV 狀態暫存器（dict + deque）
├── spread_detector.py    # IV Spread 偵測器（固定門檻 + z-score 動態門檻）
├── order_block.py        # 下單邏輯預留區塊
└── main.py               # 主程式入口
```

---

## 4. 資料流

```
mock_feed.py
  每次 Tick 攜帶：symbol / expiry_month / strike / cp / 
                  last_price / bid / ask / timestamp
       ↓ on_tick(tick) callback

iv_engine.py
  Newton-Raphson 反推（初始猜測 sigma=0.3，最多 50 次迭代）
  失敗時 fallback 到 scipy.optimize.brentq
  輸出：{ iv_mid, iv_bid, iv_ask }
       ↓

iv_store.py
  dict key: (expiry_month, strike, cp)
  每筆記錄：{
      iv_mid, iv_bid, iv_ask,
      last_ts,                    ← 供 Freshness Guard 使用
      spread_history: deque(200)  ← 供 z-score 計算使用
  }
       ↓

spread_detector.py
  ① Freshness Guard
      近月 last_ts 與遠月 last_ts 都在 STALE_MS（預設 500ms）內
      否則跳過，不觸發鬼訊號
  ② 計算可執行 IV Spread
      買近賣遠：executable_spread = iv_far_bid  - iv_near_ask
      買遠賣近：executable_spread = iv_near_bid - iv_far_ask
  ③ 固定門檻觸發
      abs(executable_spread) > FIXED_THRESHOLD（預設 0.02）
  ④ 動態 z-score 觸發（per-strike history，最少 30 個樣本）
      z = (spread_now - mean) / std > ZSCORE_THRESHOLD（預設 2.0）
  ⑤ AND / OR 模式可透過 config 切換
       ↓

order_block.py
  信號觸發時：印出信號明細到控制台
  預留區塊：TODO: 接入 Shioaji 真實下單邏輯
```

---

## 5. 關鍵設計決策

### 5.1 防止鬼訊號（Freshness Guard）
近月與遠月的 Tick 不會同時到達。若其中一方報價已過期（超過 `STALE_MS`），
則不計算 IV Spread，避免用新舊報價混合產生虛假信號。

### 5.2 波動率微笑隔離（Per-Strike Z-Score）
z-score 只在同一 `(strike, cp)` 的歷史 spread 中計算，
不跨履約價比較，避免 smile/skew 結構干擾基準線。

### 5.3 Newton-Raphson IV 反推
以牛頓迭代取代 brentq，利用 vega 作為導數，
典型 3-5 次收斂，速度快 5-10 倍；
邊界條件失敗時才回退到 brentq 作 fallback。

### 5.4 可執行 IV（Executable IV）
分別計算 iv_mid / iv_bid / iv_ask 三個 IV 值。
套利信號判斷使用可執行方向的 IV（買用 ask IV、賣用 bid IV），
避免 mid price 幻覺（bid-ask spread 在 TXO 中可達數十點）。

### 5.5 無風險利率
固定使用 `r = 0.02`（2% 年化），寫入 `config.py`。

---

## 6. 配置參數（config.py）

| 參數 | 預設值 | 說明 |
|------|--------|------|
| RISK_FREE_RATE | 0.02 | 無風險利率（年化） |
| FIXED_THRESHOLD | 0.02 | 固定門檻（IV 差值，2%） |
| ZSCORE_THRESHOLD | 2.0 | z-score 觸發門檻 |
| ZSCORE_MIN_SAMPLES | 30 | z-score 最少歷史樣本數 |
| STALE_MS | 500 | 報價新鮮度視窗（毫秒） |
| SPREAD_HISTORY_LEN | 200 | 每個 strike 保存的 spread 歷史長度 |
| SIGNAL_MODE | "OR" | 信號觸發模式（"OR" 或 "AND"） |

---

## 7. 不在範圍內（Out of Scope）

- 真實帳號登入與下單（預留區塊，不實作）
- 歷史資料回測
- 多商品並行（僅處理 TXO）
- 動態利率取得
- 除權息調整
