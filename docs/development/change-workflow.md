# 修改功能的工作順序

開始前先讀[架構導覽](README.md)，在乾淨的工作樹上找到需求對應的程式入口。每次變更先確認「讀卡端 → API → 資料庫 → 管理畫面」哪幾段會受影響，避免只改畫面或只改後端。

## API 或考勤規則

1. 從 `api_server.py` 找路由，再追到 `database/` 的管理類別；裝置請求還要檢查 `device_protocol.py` 與核准流程。
2. 確認既有桌面端和 ESP32 對請求、狀態碼、簽章與回應的依賴。若改變協定，先同步兩端與[協定文件](../DEPLOYMENT_AND_PROTOCOL.md)。
3. 在 `tests/` 加入能檢查新行為的案例，執行相關 Python 測試；若改變維運操作，同步更新[維運教程](../operations/README.md)。

## 資料表或歸檔

1. 檢查 `database/base.py` 的模型、`database/schema.py` 的版本檢查與 `database/database_manager.py` 的熱庫、年度歸檔處理。
2. 先定義舊資料如何升級及失敗時如何停止，並用暫存 SQLite 驗證；不可只靠 `create_all` 掩蓋既有結構不符。歸檔庫不保存裝置憑證。
3. 更新 schema 測試與[備份還原教程](../operations/backup.md)，說明升級前後需要保留的資料。

## 畫面或讀卡端

1. 管理頁從 `frontend/src/views/` 找畫面，追 `frontend/src/api/index.ts` 的請求及路由權限；執行 `npm run build`。
2. Windows 讀卡端從 `reader_client.py`、`reader/`、`worker/` 追卡號輸入、背景工作與離線 JSON；驗證裝置身分、補送與關閉時的行為。
3. ESP32 韌體從 `firmware/CVTA_Reader/` 追硬體、網路與 LittleFS；編譯後依[韌體測試方法](../../firmware/TESTING.md)做實機確認，更換零件時重新校對卡號及顯示器。

完成後檢查程式、測試、[系統使用文件](../PACKAGE_README.md)與相關教程是否一致；AI 協作細節另見[AI 指引](../AI_COLLABORATION.md)。
