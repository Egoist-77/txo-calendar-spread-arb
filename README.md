# TXO Calendar Spread Arbitrage（台指選擇權跨月份時間價差套利）

[![Tests](https://github.com/Egoist-77/txo-calendar-spread-arb/actions/workflows/tests.yml/badge.svg)](https://github.com/Egoist-77/txo-calendar-spread-arb/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Last Commit](https://img.shields.io/github/last-commit/Egoist-77/txo-calendar-spread-arb)](https://github.com/Egoist-77/txo-calendar-spread-arb/commits/master)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

以 Python 實作的台指選擇權（TXO）跨月份 IV Spread 套利偵測系統。

## 功能特色

- **模擬行情產生器**：內建 MockFeed，模擬 Shioaji API 的 Tick 訂閱介面
- **Black-Scholes IV 計算**：Newton-Raphson 主路徑（速度快），scipy brentq 備援
- **防鬼訊號（Freshness Guard）**：確保近/遠月報價都在 500ms 新鮮窗口內
- **可執行 IV Spread**：使用 bid/ask IV（非 mid），反映真實交易成本
- **Per-Strike Z-Score**：按 (strike, cp) 獨立計算，避免波動率微笑干擾
- **雙重觸發條件**：固定門檻 + 動態 z-score，可切換 AND / OR 模式

## 專案結構

```
txo-calendar-spread-arb/
├── calendar_spread_arb/
│   ├── __init__.py
│   ├── config.py          # 策略參數設定
│   ├── iv_engine.py       # Black-Scholes 定價與 IV 反推
│   ├── iv_store.py        # IV 資料儲存、Freshness Guard、Z-Score
│   ├── mock_feed.py       # 模擬 Tick 行情產生器
│   ├── spread_detector.py # IV Spread 信號偵測邏輯
│   ├── order_block.py     # 信號處理（目前為控制台輸出，預留下單接口）
│   └── main.py            # 主程式進入點
├── tests/
│   ├── test_iv_engine.py
│   ├── test_iv_store.py
│   └── test_spread_detector.py
└── docs/
    └── superpowers/
        ├── specs/         # 設計規格文件
        └── plans/         # 實作計畫文件
```

## 範例輸出

### 啟動畫面與狀態列

```
============================================================
台指選擇權 Calendar Spread 套利監控系統
  近月：202506  遠月：202507
  固定門檻：2.00%  z-score 門檻：2.0
  信號模式：OR
  報價新鮮度視窗：500ms
============================================================
按 Ctrl+C 停止

[03:54:30] 運行中... 已處理 120 筆 Tick | IVStore 合約數：20 | 最新：TXO202507P17200 bid=312 ask=321 iv_mid=0.2134
```

### 套利信號觸發

```
============================================================
[2026-05-27 03:54:30.574] 套利信號觸發
  商品    : TXO P 16800
  方向    : 買近月 + 賣遠月
  近月    : 202506  bid IV=0.1848  ask IV=0.1874
  遠月    : 202507   bid IV=0.2075  ask IV=0.2108
  可執行IV差: +0.0200 (+2.00%)
  觸發條件: 固定門檻(spread=+0.0200)
============================================================

============================================================
[2026-05-27 03:54:31.203] 套利信號觸發
  商品    : TXO C 17000
  方向    : 買遠月 + 賣近月
  近月    : 202506  bid IV=0.1712  ask IV=0.1739
  遠月    : 202507   bid IV=0.1923  ask IV=0.1956
  可執行IV差: -0.0227 (-2.27%)
  觸發條件: 固定門檻(spread=-0.0227) + z-score(2.31σ)
============================================================
```

> **說明：** 可執行 IV 差使用 bid/ask（非 mid），反映真實可成交價格。
> 同時觸發固定門檻與 z-score 時，觸發條件欄位會一併顯示。

## 快速開始

```bash
# 安裝依賴（可選，scipy 為 brentq 備援路徑）
pip install scipy

# 執行主程式
python -m calendar_spread_arb.main

# 執行測試
pytest tests/ -v
```

## 參數設定

編輯 `calendar_spread_arb/config.py`：

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `FIXED_THRESHOLD` | `0.02` | IV Spread 固定觸發門檻（2%） |
| `ZSCORE_THRESHOLD` | `2.0` | Z-Score 動態觸發門檻 |
| `ZSCORE_MIN_SAMPLES` | `30` | 最少樣本數才進行 z-score 計算 |
| `STALE_MS` | `500` | 報價新鮮度上限（毫秒） |
| `SIGNAL_MODE` | `"OR"` | 觸發模式：`"OR"` 或 `"AND"` |
| `NEAR_EXPIRY` | `"202506"` | 近月到期月份代碼 |
| `FAR_EXPIRY` | `"202507"` | 遠月到期月份代碼 |

## 接入真實 Shioaji API

`order_block.py` 的 `on_signal()` 函式中有完整的 Shioaji 下單範例程式碼（已註解）。
將 MockFeed 替換為真實 Shioaji 訂閱，並取消註解下單邏輯即可上線。
