# CVTA 打卡系統

提供 FastAPI 打卡後端、Vue 管理前端、Windows 桌面讀卡端與 ESP32 RFID 讀卡端。

Windows 桌面讀卡端可從托盤校正 UID 順序；開發模式的模擬讀卡也可完成校正。操作見[桌面讀卡端指南](docs/operations/desktop-reader.md#校正卡號順序)。

## 建立開發環境

準備 Python 3.13、[uv](https://docs.astral.sh/uv/)、Node.js（20.19 以上的 20.x，或 22.12 以上）與 npm。Python 套件依 `pyproject.toml`、`uv.lock` 安裝；前端套件依 `frontend/package.json`、`frontend/package-lock.json` 安裝。修改 ESP32 韌體時另需 Arduino IDE 2，板卡及函式庫見[韌體建置指南](firmware/BUILD.md)。

在獨立的開發目錄，從專案根目錄執行：

```powershell
uv sync --locked
uv run python -m unittest discover -s tests
uv run python api_server.py
```

後端預設使用 `http://127.0.0.1:16688`，並依目前工作目錄建立 `data/` 與 `logs/`。另開終端機啟動前端：

```powershell
Set-Location frontend
npm ci
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm run dev
```

`frontend/.env.example` 將開發代理指向後端預設埠；如已有 `.env`，請確認 `VITE_CVTA_API_PROXY_TARGET` 指向自己的開發後端。執行 `npm run build` 會在專案根目錄產生 `dist/`，供後端提供管理頁。完整步驟及測試說明見[本機開發與測試](docs/development/local-setup.md)。

## 文件導覽

- [系統使用文件](docs/PACKAGE_README.md)：程式位置與操作文件入口。
- [維運操作導覽](docs/operations/README.md)：按啟停、備份、裝置設定與離線排障選擇逐步教程。
- [開發文件導覽](docs/development/README.md)：架構、開發環境、修改流程與 Windows 建置。
- [AI 協作指引](docs/AI_COLLABORATION.md)：協作流程與資料使用界線；自動載入的簡版見 [AGENTS.md](AGENTS.md)。

## 專題指南

- [讀卡端韌體](firmware/README.md)
- [ESP32 USB Serial 設定工具](docs/operations/esp32-serial-tool.md)
- [部署與裝置協定](docs/DEPLOYMENT_AND_PROTOCOL.md)
- [前端](frontend/README.md)
