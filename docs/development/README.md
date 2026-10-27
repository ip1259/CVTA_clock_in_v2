# 開發文件導覽

原始碼以 [GitHub 專案](https://github.com/CVTA-Engineers/CVTA-Attendance-System)為準。本目錄說明程式架構與常見開發任務；執行環境的操作方法另見[維運導覽](../operations/README.md)。

## 打卡資料流

1. Windows 桌面端或 ESP32 讀取卡片 UID，帶裝置 UUID、時間戳與 HMAC 簽章呼叫 `POST /api/v1/punch`。
2. FastAPI 驗證裝置身分、核准與暫停狀態，查 UID 對應的員工，寫入 SQLite 熱庫 `data/punch_hot.db`，回傳打卡結果。
3. 網路故障時，桌面端存入本機 `data/offline_punches.json`，ESP32 存入 LittleFS；恢復後以原裝置身分補送。管理前端用 `/api/v1` 查詢與管理資料，管理員登入使用 JWT。

詳細簽章與 schema 規則見[部署與裝置協定](../DEPLOYMENT_AND_PROTOCOL.md)。

| 要做的事 | 教程 |
| --- | --- |
| 第一次架設本機環境、啟動與測試 | [本機開發與測試](local-setup.md) |
| 修改 API、資料表、前端或讀卡端 | [修改功能的工作順序](change-workflow.md) |
| 建置 Windows 可執行檔 | [Windows 建置](build-windows.md) |

## 程式入口

| 範圍 | 主要位置 |
| --- | --- |
| API 與驗證 | `api_server.py`、`device_protocol.py`、`database/device_manager.py` |
| 資料表、遷移、考勤與班表 | `database/base.py`、`database/schema.py`、`database/*_manager.py` |
| 管理介面 | `frontend/src/views/`、`frontend/src/api/index.ts`、`frontend/src/router/index.ts` |
| Windows 讀卡端與離線補送 | `reader_client.py`、`reader/`、`worker/` |
| ESP32 韌體 | `firmware/CVTA_Reader/`，另見[韌體指南](../../firmware/GUIDE.md)與[更換 LCD 校正](../../firmware/tests/TFT_LCD_TEST/DETAILS.md#更換模組後校正畫面位置) |
| ESP32 USB Serial 設定工具 | `esp32_serial_tool.py`、`esp32_serial_protocol.py`；操作見[USB 工具教程](../operations/esp32-serial-tool.md) |

桌面端只有以 `--dev-mode` 啟動才顯示「測試模式 → 模擬讀卡」。模擬讀卡只替代讀卡機輸入；後續仍走 `PunchClient._on_card_scanned`、裝置核准檢查、簽章請求與離線補送。操作方法見[設定桌面讀卡端](../operations/desktop-reader.md#測試模式與模擬讀卡)。

熱庫 schema 目前為第 3 版；未知結構會阻止後端啟動。年度歸檔函式存在，但目前未見自動呼叫。更動資料結構時，連同[備份與還原](../operations/backup.md)一起檢查。遠端新增卡片使用裝置命令與一次性憑證，詳見[裝置協定](../DEPLOYMENT_AND_PROTOCOL.md#遠端新增空卡)。
