# CVTA 打卡系統

提供 FastAPI 打卡後端、Vue 管理前端、Windows 桌面讀卡端與 ESP32 RFID 讀卡端。

## 交接文件

- [可執行檔交接包入口](docs/HANDOFF_README.md)：複製為交接包根目錄的 `README.md`，與維運手冊及可執行檔一起交付；原始碼留在 GitHub。
- [維運交接](docs/OPERATIONS_HANDOFF.md)：部署現況、裝置管理、人工備份與故障處理。
- [開發架構總覽](docs/DEVELOPER_OVERVIEW.md)：打卡資料流、修改入口與建置測試。
- [AI 協作指引](docs/AI_COLLABORATION.md)：協作流程與資料使用界線；自動載入的簡版見 [AGENTS.md](AGENTS.md)。

## 專題指南

- [讀卡端韌體](firmware/README.md)
- [部署與裝置協定](docs/DEPLOYMENT_AND_PROTOCOL.md)
- [前端](frontend/README.md)
