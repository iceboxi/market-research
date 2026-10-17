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
| 三山 | sakata_three_mountains_triple_top | 已實作（研究版），三峰與確認後頸線跌破 | pivot／價格調整假設仍需市場驗證 |
| 三山 | sakata_three_mountains_head_shoulders | 已實作（研究版），頭肩頂確認後頸線跌破 | 肩部容差與量化門檻仍屬研究假設 |
| 三川 | sakata_morning_star | 陰線、小實體、陽線反轉 | 前段下跌、缺口、實體及收復比例 |
| 三川 | sakata_evening_star | 陽線、小實體、陰線反轉 | 前段上漲、缺口、實體及回落比例 |
| 三空 | sakata_three_gaps_up | 已實作，三個全區間向上缺口 | 台股未查證公司行動必須 abstain |
| 三空 | sakata_three_gaps_down | 已實作，三個全區間向下缺口 | 台股 abstain；不等於反向下單 |
| 三兵 | sakata_three_soldiers | **既有紅三兵 v0.1.0，已實作** | 不修改原有門檻 |
| 三兵 | sakata_black_three_crows | 三根陰線偏空型態 | 是否鏡射、前段漲勢及下影線門檻 |
| 三法 | sakata_rising_three_methods | 已實作五 K 延續研究版 | 長期績效與實際交易仍未驗證 |
| 三法 | sakata_falling_three_methods | 已實作五 K 延續研究版 | 不使用現有做多回測 |

## 策略生命週期

- draft：只保留待決條件；不得進入 runtime registry。
- specified：量化條件、輸入型態、無效條件與 test vectors 已確認，但未實作。
- implemented：實際 Plugin 與測試已完成；**仍須在 runtime config 明確啟用**。
- validated_for_research：完成獨立回播與整合驗收，不表示已證明獲利。

## 時間、行情與回測契約

所有策略僅能在 K 棒完整收盤後確認；三山需要等待右側 pivot K 棒確認，**不可把事後確認的型態回填到高點當日當作可交易訊號**。三空要處理除權息與缺口定義；暫時只當作 observation。每個策略需要記錄 `strategy_id`、`version`、`signal_confirmation_time`、input SHA-256、調整價格基礎與 params。市場資料缺漏、NaN、非正價格或未完成交易日須拒絕或明確報告。

每個候選未來完成規格後需準備：正例、反例、恰等於閾值的邊界例、資料不足、資料異常、prefix/no-lookahead、同快照重跑一致性，以及 Scan／Backtest 共用資料契約測試。型態辨識和進出場規則分開定義；目前回測固定持有五個交易日只是研究假設。

**目前階段**：十種型態皆有研究版 Plugin；驗收與市場有效性是不同階段。三山的 pivot 延遲與三空公司行動限制必須保留。


## 晨星：implemented v0.1.0（預設停用）

已決定第一版研究量化規格，詳細條件與資料契約見 [morning_star.yaml](morning_star.yaml)，正例／邊界／負例／資料不足／異常資料情境見 [morning_star.yaml 測試夾具](../../tests/fixtures/morning_star.yaml)。前 5 根 K 棒收盤首尾至少下跌 2%；第一根陰線實體至少占當日區間 60%；第二根實體不大於第一根實體 30%，且星線實體最高點不得超出第一根陰線收盤（不要求影線完全跳空）；第三根陽線實體至少占區間 50%，收盤至少回收第一根陰線實體的 50%。比較門檻包含等號，陰陽線判斷為嚴格不等號。第三根收盤後才可確認。所有門檻皆為本專案提出的**研究假設**，不是被證實有效的酒田原始標準。

**狀態 = implemented，預設 enabled: false。** Runtime 實作位於 `src/market_research/morning_star.py`，並已列入 Strategy Registry。現有 fixtures 已由真正的策略程式計算驗收，包含未完成型態不可提前確認與次日開盤進場的研究回測整合測試。此狀態僅代表工程實作與測試完成，不表示市場有效性、真實可成交性或可自動交易。


## 暮星：implemented v0.1.0（正式停用）

詳細量化條件見 [evening_star.yaml](evening_star.yaml)，案例見 [evening_star fixtures](../../tests/fixtures/evening_star.yaml)。暮星研究版採晨星的價格方向鏡像：先有五根收盤價累積漲幅至少 2%，首根強陽實體／振幅至少 60%，次根星體不超過首根實體 30%、且星體最低點不低於第一根收盤價；第三根強陰實體／振幅至少 50%，收盤回落首根陽線實體至少 50%。不強制影線跳空，嚴格陰陽比較，門檻含等號。數值為研究假設而非獲利保證。訊號只在第三根完成後確認；偏空觀察不等於做空訂單，目前通用研究 Runner 僅會輸出掃描與歷史觀察，不使用只做多回測模型。


## 黑三兵（Three Black Crows） v0.1.0 — Implemented / disabled

本專案採與紅三兵方向對稱的研究型定義：之前五根收盤價首尾上漲至少 2%；接著三根陰線且收盤逐根下降；後兩根開盤位於前一根陰線實體範圍；每根陰線實體佔振幅至少 50%、下影線最多 25%。合法零振幅歷史 K 棒不當成損壞資料，但零振幅訊號 K 棒不能形成黑三兵。第三根完成後才確認。完整參數見 [black_three_crows.yaml](black_three_crows.yaml)，測試案例見 [fixtures](../../tests/fixtures/black_three_crows.yaml)。這些比例是研究假設，不代表傳統唯一標準或經驗證的預測效果。策略 `enabled: false`，研究 Runner 僅輸出偏空觀察，不會執行做空交易或套用做多回測。


## 三空與三山 v0.1.0（研究限定，預設停用）

向上與向下三空：要求 4 個連續交易日形成 3 個完整 high/low 價格窗口，缺口至少 0.2%，先前五根收盤價方向變化至少 2%。TWSE 未調整歷史價格缺乏可驗證公司行動資料，直接 abstain（不會匹配）；美股使用 Yahoo adjusted analysis OHLC，結果只代表調整價格窗口，不代表可成交跳空。三重頂與頭肩頂：確認左右各兩根完整 K 棒的局部 pivot，三峰與頸線判定後，必須在最新完成 K 棒首次跌破頸線 0.2%；右側確認之前不會發訊號，且不倒填高點日。所有數值都是本專案研究假設，並非獲利證明。
