# CVTA 打卡系統交接包

本頁供可執行檔交接包使用。請將本檔以 `README.md` 名稱、[維運手冊](OPERATIONS_HANDOFF.md)以 `OPERATIONS_HANDOFF.md` 名稱，放在**同一個交接包根目錄**。原始碼、開發文件與 AI 協作指引保留在 [GitHub 專案](https://github.com/ip1259/CVTA_clock_in_v2)；接手開發者須先取得該 repo 的存取權。

## 開始接手

1. 先讀[維運手冊](OPERATIONS_HANDOFF.md)，確認啟動捷徑的目標、起始位置、資料庫路徑及備份現況。
2. 保持打包後端的整個 `api_server/` 目錄完整；目前 Windows v0.1.1 版的入口是 `api_server/api_server_app.exe`。目前同版桌面端入口是 `reader_client/reader_client_app.exe`；其他封裝若為單一 exe，依該版實際目錄記錄。不要只取出 exe 而遺漏相鄰的 `_internal/`。
3. 記錄本包的版本、對應 Git commit 或 tag、打包日期與可執行檔 SHA-256。更新程式時一併更新這些資訊和維運手冊，再交付新包。

## 本次交付資訊（打包時填寫）

| 項目 | 實際值 |
| --- | --- |
| 版本及對應 Git commit／tag | 待填 |
| 打包日期與執行人 | 待填 |
| 後端／桌面端實際檔案位置 | 待填 |
| SHA-256 檔案或校驗紀錄 | 待填 |

交接包不包含原始碼、實際資料庫、離線紀錄或裝置憑證。詳細程式結構見 GitHub 上的[開發架構總覽](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/docs/DEVELOPER_OVERVIEW.md)，裝置協定與韌體指南也以 GitHub 版本為準。
