# CVTA 打卡系統使用文件

CVTA 系統由 Windows 後端與管理網頁、Windows 桌面讀卡端及 ESP32 獨立讀卡端組成。管理網頁目前位於 `http://192.168.100.23:16688/`；原始碼與開發說明位於 [GitHub 專案](https://github.com/ip1259/CVTA_clock_in_v2)。

## 操作文件

新增空卡：管理員登入管理網頁，在「卡片管理 → 新增卡片」選擇已核准、未暫停的 Windows 或 ESP32 讀卡端。等待讀卡端顯示加卡模式，在 30 秒內刷一張卡，管理頁會顯示等待、成功、卡號已存在或逾時結果；讀卡端也會顯示或通知刷卡結果。若讀卡端顯示結果未確認，請在管理頁核對。讀卡端在第一次刷卡或逾時後自動恢復打卡；加卡不使用離線打卡補送。讀卡端操作細節見下方兩份設定教程。

從[維運操作導覽](operations/README.md)選擇目前要做的事：

- [啟停後端](operations/server.md)及確認管理網頁
- [備份與還原資料庫](operations/backup.md)
- [設定 Windows 桌面讀卡端](operations/desktop-reader.md)或 [ESP32 讀卡端](operations/esp32-reader.md)
- [處理離線紀錄與打卡異常](operations/offline.md)
- [安裝或更新後檢查](operations/verification.md)

## 程式位置

現行 v0.2.1 Windows 版的後端入口是 `api_server/api_server_app.exe`，管理網頁已包含在 `api_server/_internal/dist/`；桌面端入口是 `reader_client/reader_client_app.exe`。兩者都需保留完整資料夾及其 `_internal/`。程式使用相對路徑存取資料庫與日誌，實際位置取決於啟動時的工作目錄，查找方法見[啟停後端](operations/server.md)。

封包內的 `firmware/CVTA_Reader/` 是 ESP32 原始碼；依[韌體建置指南](firmware/BUILD.md)編譯及燒錄，並完成[現場測試](firmware/TESTING.md)。
