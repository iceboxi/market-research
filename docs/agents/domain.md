# Domain docs

採 single-context：root `GLOSSARY.md` 與 `docs/adr/`。探索或變更領域規則前閱讀存在的 glossary 與相關 ADR；不存在就直接繼續，等實際釐清術語或重大取捨時再由 domain-modeling 建立。

沿用 repository 的 metric、state、source 與 price basis 名稱；不要把出表日期、實際公開時間、資料期間或抓取時間當成同一概念。

Glossary 只記領域定義，ADR 只記需要長期保留的決策理由；需求與工作狀態留在 GitHub，實作契約依有效 spec 與已確認決策。Design Doc 為獨立技術說明，不取代 spec。

輸出與既有 ADR 衝突時明確指出（例：「與 ADR-000N 衝突，但值得重新討論，因為…」），不默默覆寫。需要的概念不在 glossary 時，先確認不是自創用語；確為缺口則記下交給 domain-modeling。
