# TW05 來源使用條件查證

查核：2026-10-20；範圍為 2330 三表來源與公開出口，技術連通性另由 runner 驗證。

> **2026-10-29 使用者決策（優先於下文的出口限制）**：先穩定研究結果，暫不以轉發授權阻擋發布；可採用其他免費來源，但必須保留來源出處與日期。依此，TWSE `t187ap03_L` 失敗時改用 FinMind `TaiwanStockInfo` 取得公司簡稱與產業別，公開快照以 `finmind_stock_info_v1` policy 標示；發行股數等 profile 數值仍只取自 TWSE。下文保留為當時的查證紀錄。

> **#114 估值檢視區**：同一決策下採用 FinMind `TaiwanStockPER`（近 5 年每日本益比，查詢起點為 cutoff 前 5 年）。報告與 Artifact 保存百分位、本益比區間、樣本數、日期範圍、最新一筆本益比與查詢 URL；公開快照因 20,000 bytes 上限只保存其中的數值（查詢 URL 由代碼與窗口起點重建）。兩者都不保存原始每日序列。

## FinMind

[三表 API](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/) 的單股查詢在 [Free](https://finmind.github.io/Pricing/) 範圍，限非商業用途，每小時 300 次、註冊 600 次；各方案皆禁止原始資料再散布及鏡像 API，使用須標示 FinMind。[SDK Apache-2.0](https://github.com/FinMind/FinMind/blob/master/LICENSE) 僅是程式授權，不能據此公開 API payload。

[使用條款第 4 節](https://finmind.github.io/PrivacyPolicy/) 與 [Disclaimer 第 3 節](https://finmind.github.io/Disclaimer/) 要求對外資料用途自行確認原來源授權。查閱上述文件，未找到「研究報告必要精簡事實數值」或「衍生指標」的專門允許／禁止條款，兩項均列 `not_verified`；不能因刪減列數就宣稱已獲再散布授權，也不能擴張為禁止所有研究。

## TWSE

官方 [損益 91998](https://data.gov.tw/dataset/91998) 與 [資產負債 94831](https://data.gov.tw/dataset/94831) 皆列免費、每三月更新、政府資料開放授權條款第 1 版；[OGDL](https://data.gov.tw/license) 允許重製、散布與衍生利用，須顯名。可公開由這些 dataset **獨立取得**的必要數值與衍生值，附提供機關、dataset 名稱、年份、版本與授權連結；不將此授權擴及整個 MOPS／IR。

兩個 catalog 明列 EPS「元」、部分股數「股」，卻未明列其他金額的統一單位；不能只憑慣例設為仟元。runner 須以同公司、同期原始財報逐欄核對倍率與單季／累計語意，未通過欄位保留 unknown。本次未確認同授權的現金流 dataset。

## TSMC IR

[年度／期中財報](https://investor.tsmc.com/english/financial-reports) 可免費閱讀；[主站使用條款](https://www.tsmc.com/english/legal_and_trademark) 適用主站與關聯網站，僅明授個人非商業瀏覽，並對重發布、重製及衍生內容要求事前書面同意。這是明示內容利用限制，全面重發布不在明授範圍；條款未單獨界定純財務事實與少量 oracle 數值，其公開出口列 `not_verified`。必要引用仍須個案評估，不能由 [著作權法第 52、64、65 條](https://law.moj.gov.tw/LawClass/LawAll.aspx?PCode=J0070017) 推出固定筆數的全面許可。

## 本次可執行出口

採用契約：probe 不保存／上傳 raw JSON、PDF 或抽取全文。公開 Artifact 僅放 URL、頁碼、期別、觀測時間、完整回應 hash、欄位名稱、coverage、程式產生的通過／差異結果；不放原值、差額或可還原值。這是縮小出口的工程決策，並非來源明授此格式。IR 可定位獨立核對依據；公開必要 oracle 數字先從已開放的 TWSE dataset 獨立取得。FinMind 精簡數值、衍生值與 IR 數值各自保留 `not_verified`，只限制依賴該出口的後續能力，其他 workflow 照常交付。
