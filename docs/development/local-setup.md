# 本機開發與測試

本頁只處理開發環境，現場可執行檔的啟停依[維運教程](../operations/server.md)。測試使用暫存資料，不使用現場的 `data/`、`logs/`、裝置憑證或備份。

## Python 後端

1. 在 repo 根目錄確認 `.python-version` 與 `pyproject.toml`；目前要求 Python 3.13。安裝 `uv` 與該版本 Python，執行 `uv sync --locked` 建立符合 `uv.lock` 的環境。若既有 `.venv` 指向已移除的 Python，先修復或重建該本機環境再繼續。
2. 執行 `uv run python api_server.py`。預設監聽 `0.0.0.0:16688`；首次執行會依工作目錄建立熱庫與日誌，故開發前先確認目前位於 repo 根目錄，且沒有指向現場資料的設定。
3. 開啟 `http://127.0.0.1:16688/`。若尚未建前端，根路徑會回報找不到 `dist`；API 仍可啟動。跨機部署須另設定 `CVTA_ADMIN_SECRET_KEY` 並更換預設管理員密碼，詳見[部署與協定](../DEPLOYMENT_AND_PROTOCOL.md)。

## 管理前端

1. 進入 `frontend/`，執行 `npm ci`。若尚無本機 `.env`，執行 `Copy-Item .env.example .env`；範例把 `VITE_CVTA_API_PROXY_TARGET` 設為後端預設的 `http://127.0.0.1:16688`。確認本機位址後執行 `npm run dev`。若未設此變數，`vite.config.ts` 預設指向 `http://127.0.0.1:8000`，與後端預設埠不同。
2. 要讓後端直接提供管理頁，於 `frontend/` 執行 `npm run build`；Vite 會產生 repo 根目錄的 `dist/`。重新啟動後端後，再開啟其首頁確認頁面可用。

## 測試與檢查

1. 從 repo 根目錄執行 `uv run python -m unittest discover -s tests`；桌面端測試會使用 Qt offscreen。若測試無法匯入套件，先核對是否真的使用 `uv` 建好的 Python 3.13 環境。
2. 修改前端後，在 `frontend/` 執行 `npm run build`，確認 TypeScript 與 Vite 建置成功。修改 ESP32 時，依[Build 指南](../../firmware/BUILD.md)編譯，硬體行為另依[現場測試方法](../../firmware/TESTING.md)驗證。
3. 記錄實際跑過的檢查與結果；不能在本機完成的實機測試，明確列為待現場驗證。
