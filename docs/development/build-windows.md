# 建置 Windows 可執行檔

此頁說明從原始碼建立後端與桌面端程式。後端的管理前端須先建置，才會被 `api_server.spec` 納入。

1. 依[本機開發與測試](local-setup.md)建立 Python 3.13 環境並執行 Python 測試；確認目前原始碼版本與測試結果。
2. 在 `frontend/` 執行 `npm run build`，確認 repo 根目錄產生 `dist/index.html`。
3. 在 Windows、從 repo 根目錄依序使用 `api_server.spec` 與 `reader_client.spec` 執行 PyInstaller。兩份 spec 目前均使用 onedir 模式，因此每個程式都有自己的資料夾。
4. 確認後端資料夾內有 `api_server_app.exe` 與 `_internal/dist/index.html`，桌面端資料夾內有 `reader_client_app.exe`；保留整個 `_internal/`，不能只取出 exe。
5. 在乾淨的測試位置啟動後端，確認管理網頁可開；再啟動桌面端，確認托盤圖示、裝置連線與讀卡。檢查啟動工作目錄，避免誤用開發或現場資料庫。

舊版執行檔可能採不同資料夾結構；以目前 repo 的 spec 與實際建置結果為準。程式安裝後的操作檢查見[維運檢查](../operations/verification.md)。
