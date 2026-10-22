# CVTA AI 協作指引

本文件補充根目錄 [`AGENTS.md`](../AGENTS.md)，供 AI 協作開發時閱讀；給人看的系統地圖見[開發文件導覽](development/README.md)。

## 開始任務

1. 確認 repo 根目錄與 `git status`，閱讀本次相關的程式及既有文件。涉及現場部署先讀[維運操作導覽](operations/README.md)及對應教程；涉及裝置驗證、資料庫升級或韌體時，再讀[部署與協定](DEPLOYMENT_AND_PROTOCOL.md)、[韌體指南](../firmware/GUIDE.md)。
2. 追查實際資料流與失敗路徑：讀卡端 → 裝置簽章／核准 → `/api/v1/punch` → UID 對應員工 → 熱資料庫；斷線時另查桌面端 JSON 或 ESP32 LittleFS 佇列。不要僅憑單一介面畫面推斷資料已入庫。
3. 實作時維持現有 API、裝置協定、資料庫版本及離線補送相容性；若任務需要改動契約，先指出受影響的客戶端、遷移與驗收項目。

## 資料與驗證

- 先確認程序的**工作目錄**再解讀相對路徑。`data/punch_hot.db`、`data/archives/` 是後端資料；桌面端的 `data/offline_punches.json` 是該端本機資料，ESP32 事件則在 LittleFS。不要把這些檔案直接用作自動化測試輸入。
- 不讀寫或提交現場資料、`logs/`、`%LOCALAPPDATA%\CVTAClockIn\device.json`、密碼、JWT 或裝置密鑰；文件只放非機密設定與可重現的操作步驟。需要樣本時由測試建立暫存 SQLite、假裝置身分或模擬請求。
- 後端與裝置協定變更，執行相關 `tests/` 測試；前端變更執行 `npm run build`；桌面端留意 Qt offscreen 測試；ESP32 先依 Build 指南驗證編譯，實機部分依測試方法列出尚需現場確認的項目。回報測試結果，不以「預期可用」代替驗證。
- 操作方式、部署方式或行為有變更時，更新對應的[維運教程](operations/README.md)、[開發教程](development/README.md)及 `README.md` 導覽；同步檢查[系統使用文件](PACKAGE_README.md)與所有 `operations/` 頁面，確認脫離原始碼目錄仍能閱讀。保持本指引和 `AGENTS.md` 精簡，細節連回單一主題文件。
