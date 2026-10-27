# CVTA 打卡系統使用文件

CVTA 系統由 Windows 後端與管理網頁、Windows 桌面讀卡端及 ESP32 獨立讀卡端組成。管理網頁目前位於 `http://192.168.100.23:16688/`；原始碼與開發說明位於 [GitHub 專案](https://github.com/CVTA-Engineers/CVTA-Attendance-System)。

## 操作文件

新增空卡：管理員登入管理網頁，在「卡片管理 → 新增卡片」選擇已核准、未暫停的 Windows 或 ESP32 讀卡端。等待讀卡端顯示加卡模式，在 30 秒內刷一張卡，管理頁會顯示等待、成功、卡號已存在或逾時結果；讀卡端也會顯示或通知刷卡結果。若讀卡端顯示結果未確認，請在管理頁核對。讀卡端在第一次刷卡或逾時後自動恢復打卡；加卡不使用離線打卡補送。讀卡端操作細節見下方兩份設定教程。

Windows 桌面端一般啟動時不顯示測試模式。需要模擬讀卡時，以 `reader_client_app.exe --dev-mode` 啟動，才可在托盤選單選「測試模式 → 模擬讀卡」輸入卡號。這會使用現有裝置身分送出正式打卡或加卡請求，斷線時打卡可能留待補送；操作前先告知管理員。輸入方式與結果核對見[桌面讀卡端測試模式](operations/desktop-reader.md#測試模式與模擬讀卡)。

Windows 桌面端的「校正卡號順序」可直接從一般模式托盤選單使用。輸入同一張實卡既有 UID，60 秒內刷卡，看到 `UID MATCH` 才正式打卡；開發模式也可在等待期間用「模擬讀卡」輸入原始 UID 完成校正。校正失敗或逾時時須重新校正。步驟見[桌面讀卡端校正](operations/desktop-reader.md#校正卡號順序)。

從[維運操作導覽](operations/README.md)選擇目前要做的事：

- [啟停後端](operations/server.md)及確認管理網頁
- [備份與還原資料庫](operations/backup.md)
- [設定 Windows 桌面讀卡端](operations/desktop-reader.md)或 [ESP32 讀卡端](operations/esp32-reader.md)；ESP32 USB 操作另見[Serial 設定工具](operations/esp32-serial-tool.md)
- [處理離線紀錄與打卡異常](operations/offline.md)
- [安裝或更新後檢查](operations/verification.md)

## 程式位置

現行 v0.2.1 Windows 版的後端入口是 `api_server/api_server_app.exe`，管理網頁已包含在 `api_server/_internal/dist/`；桌面端入口是 `reader_client/reader_client_app.exe`。另可由原始碼使用 `esp32_serial_tool.spec` 建置 `esp32_serial_tool/esp32_serial_tool_app.exe`，供 ESP32 USB 設定。各程式都需保留完整資料夾及其 `_internal/`。後端與桌面讀卡端使用相對路徑存取資料庫與日誌，實際位置取決於啟動時的工作目錄，查找方法見[啟停後端](operations/server.md)。

原始碼封包內的 `firmware/CVTA_Reader/` 是 ESP32 韌體；依[韌體建置指南](../firmware/BUILD.md)編譯及燒錄，並完成[現場測試](../firmware/TESTING.md)。
