# 酒田五法：策略規格草案 v0.1

本文件只定義研究用型態，**不會自動啟用策略或產生交易指令**。機器可讀目錄為 [catalog.yaml](catalog.yaml)。執行時仍以 `config/strategies.yaml` 與 `src/market_research/strategies.py` 為準。

## 定義及歧義

酒田五法通常分為三山、三川、三空、三兵、三法。教材對三川、三法的用法並非完全一致；此處三川採晨星／暮星的三根 K 棒版本，三法採上升／下降三法的整理延續型態，**不是聲稱涵蓋所有傳統解讀**。各門檻均是未決研究假設，不得憑名稱自行填入。

參考：
- 野村證券名詞解釋：https://www.nomura.co.jp/terms/japan/sa/A01981.html
- auじぶん銀行術語：https://www.jibunbank.co.jp/products/foreign_deposit/glossary/YST2036.html

## 個別型態範圍

| 分類 | 候選 ID | 初步觀察 | 尚待決定 |
|---|---|---|---|
| 三山 | sakata_three_mountains_triple_top | 三個已確認高點與跌破頸線 | pivot 右側確認、峰值誤差、頸線算法 |
| 三山 | sakata_three_mountains_head_shoulders | 中峰高於左右肩與頸線跌破 | 肩高容差、趨勢、確認時間 |
| 三川 | sakata_morning_star | 陰線、小實體、陽線反轉 | 前段下跌、缺口、實體及收復比例 |
| 三川 | sakata_evening_star | 陽線、小實體、陰線反轉 | 前段上漲、缺口、實體及回落比例 |
| 三空 | sakata_three_gaps_up | 三次連續向上跳空 | 全區間或開盤缺口、最小幅度、除權息 |
| 三空 | sakata_three_gaps_down | 三次連續向下跳空 | 同上；觀察不等於反向下單 |
| 三兵 | sakata_three_soldiers | **既有紅三兵 v0.1.0，已實作** | 不修改原有門檻 |
| 三兵 | sakata_black_three_crows | 三根陰線偏空型態 | 是否鏡射、前段漲勢及下影線門檻 |
| 三法 | sakata_rising_three_methods | 強勢 K、整理 K、續漲確認 K | 整理根數、包覆範圍、突破標準 |
| 三法 | sakata_falling_three_methods | 弱勢 K、整理 K、續跌確認 K | 同上；不可默認反向下單 |

## 策略生命週期

- draft：只保留待決條件；不得進入 runtime registry。
- specified：量化條件、輸入型態、無效條件與 test vectors 已確認，但未實作。
- implemented：實際 Plugin 與測試已完成；**仍須在 runtime config 明確啟用**。
- validated_for_research：完成獨立回播與整合驗收，不表示已證明獲利。

## 時間、行情與回測契約

所有策略僅能在 K 棒完整收盤後確認；三山需要等待右側 pivot K 棒確認，**不可把事後確認的型態回填到高點當日當作可交易訊號**。三空要處理除權息與缺口定義；暫時只當作 observation。每個策略需要記錄 `strategy_id`、`version`、`signal_confirmation_time`、input SHA-256、調整價格基礎與 params。市場資料缺漏、NaN、非正價格或未完成交易日須拒絕或明確報告。

每個候選未來完成規格後需準備：正例、反例、恰等於閾值的邊界例、資料不足、資料異常、prefix/no-lookahead、同快照重跑一致性，以及 Scan／Backtest 共用資料契約測試。型態辨識和進出場規則分開定義；目前回測固定持有五個交易日只是研究假設。

**目前優先順序**：先將晨星的長／短實體、回補幅度和跳空政策定義清楚，再實作測試；下一批考慮暮星、黑三兵。三山與三空因 pivot 時間及價格調整較敏感，暫後。


## 晨星：specified v0.1.0（尚未實作）

已決定第一版研究量化規格，詳細條件與資料契約見 [morning_star.yaml](morning_star.yaml)，正例／邊界／負例／資料不足／異常資料情境見 [morning_star.yaml 測試夾具](../../tests/fixtures/morning_star.yaml)。前 5 根 K 棒收盤首尾至少下跌 2%；第一根陰線實體至少占當日區間 60%；第二根實體不大於第一根實體 30%，且星線實體最高點不得超出第一根陰線收盤（不要求影線完全跳空）；第三根陽線實體至少占區間 50%，收盤至少回收第一根陰線實體的 50%。比較門檻包含等號，陰陽線判斷為嚴格不等號。第三根收盤後才可確認。所有門檻皆為本專案提出的**研究假設**，不是被證實有效的酒田原始標準。

**狀態 = specified，不是 implemented。** 目前沒有晨星的 runtime Strategy class，也沒有啟用它；新增的 fixture 用於規格一致性測試，不代表型態偵測演算法已經通過正確性驗收。後續須依據此規格實作獨立策略、逐一讓 fixture 由真正的算法計算通過，並完成 Scan／Backtest 整合測試，才可提升狀態。
