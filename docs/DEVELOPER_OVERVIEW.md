# CVTA 開發架構總覽

## 一條打卡資料流

Windows 桌面讀卡端或 ESP32 讀到 UID 後，以裝置 UUID、時間戳與 HMAC 簽章呼叫 FastAPI 的 `POST /api/v1/punch`。後端先驗證裝置身分與核准狀態，再依卡片 UID 找到員工，寫入 SQLite 熱資料庫 `data/punch_hot.db`，回傳結果。管理前端透過 `/api/v1` 查詢及管理人員、卡片、班表、紀錄與裝置；管理員登入使用 JWT。裝置註冊、簽章、拒絕狀態及 schema 升級的詳細契約見[部署與裝置協定](DEPLOYMENT_AND_PROTOCOL.md)。

網路故障時，桌面端將打卡存入自身工作目錄的 `data/offline_punches.json`，ESP32 存入 LittleFS，之後各以原裝置身分補送。桌面端只將網路／逾時或伺服器 5xx 視為離線；401／403 不應視為成功。ESP32 的狀態與現場測試見[韌體指南](../firmware/GUIDE.md)及[測試方法](../firmware/TESTING.md)。

## 修改入口

| 需求 | 先查看 |
| --- | --- |
| API、登入、裝置驗證 | `api_server.py`、`device_protocol.py`、`database/device_manager.py` |
| 資料表、schema 升級、年度歸檔 | `database/base.py`、`database/schema.py`、`database/database_manager.py` |
| 考勤、人員、卡片、班表及匯出 | `database/*_manager.py`、`web/export.py` |
| 管理畫面與 API 呼叫 | `frontend/src/views/`、`frontend/src/api/index.ts`、`frontend/src/router/index.ts` |
| Windows 讀卡、離線補送、診斷 | `reader_client.py`、`reader/`、`worker/` |
| ESP32 讀卡與顯示 | `firmware/CVTA_Reader/`、[接線與設定](../firmware/GUIDE.md) |

熱資料庫 schema 目前為第 1 版；啟動後端時會檢查或升級已知結構，未知結構會阻止啟動。`data/archives/` 存放可能存在的年度資料庫，但目前未見歸檔函式自動呼叫。修改資料模型時應同時檢查遷移、測試與[維運備份步驟](OPERATIONS_HANDOFF.md#人工備份與還原)。

## 開發與驗證

- 原始碼與開發、AI 文件留在 GitHub。現場可執行檔交接包根目錄只需[交接包入口](HANDOFF_README.md)和[維運手冊](OPERATIONS_HANDOFF.md)，以及完整的後端與桌面端打包資料夾；複製文件時分別命名為 `README.md`、`OPERATIONS_HANDOFF.md`。記錄該包對應的 Git commit／tag，避免二進位版本與文件不一致。
- Python 需求與版本見 `pyproject.toml`、`.python-version`；後端入口是 `api_server.py`，預設監聽埠 16688。`main.py` 目前只是佔位入口。管理前端由 Vue 3／TypeScript／Vite 建立，於 `frontend` 執行 `npm install`、`npm run dev`；正式建置執行 `npm run build`，輸出至專案根目錄 `dist/`。後端在該目錄存在時提供 SPA；打包規則見 `api_server.spec` 與 `reader_client.spec`。
- Python 先依 `uv.lock` 建立 Python 3.13 環境（`uv sync`），再從專案根目錄執行 `uv run python -m unittest discover -s tests`；桌面端測試使用 Qt offscreen 模式。前端變更至少執行 `npm run build`。ESP32 韌體依[Build 指南](../firmware/BUILD.md)編譯，硬體行為依[現場驗收](../firmware/TESTING.md#正式韌體現場驗收)確認。
- 測試應使用暫存資料與測試裝置；`data/`、`logs/`、裝置憑證及現場備份不屬於開發樣本。協作規則見[AI 協作指引](AI_COLLABORATION.md)。
