# CVTA 打卡系統維運交接

本文件可放在可執行檔交接包根目錄，與該目錄的 `README.md` 一起使用。原始碼與詳細技術指南保留在 [GitHub 專案](https://github.com/ip1259/CVTA_clock_in_v2)；部署前須確認本包版本對應的 commit 或 tag。

## 部署現況與啟停

- 集中伺服器目前固定 IP 為 `192.168.100.23`，後端運行於 Windows，使用者 `startup` 登入後自動啟動。後端預設監聽 `0.0.0.0:16688`；實際監聽值可由 `CVTA_CLOCKIN_API_HOST`、`CVTA_CLOCKIN_API_PORT` 覆寫。
- 管理前端與後端同機，已隨後端 exe 打包；目前 Windows v0.1.1 包的前端檔位於 `api_server/_internal/dist/`，無須在現場另行執行 `npm run build`。交接包根目錄下須保留完整的 `api_server/` 資料夾，入口為 `api_server/api_server_app.exe`，不可只複製該 exe。
- 桌面讀卡端可裝在接有實體感應讀卡機的 Windows 電腦；目前 Windows v0.1.1 包的入口為 `reader_client/reader_client_app.exe`，須保留整個資料夾。ESP32 讀卡端接上電源即可獨立運行，但仍須完成接線、網路、時間同步與裝置核准。零件可替換；更換讀卡器或顯示模組後，須依 GitHub 上的[韌體指南](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/firmware/GUIDE.md)重新校對 UID、接線及畫面。

**現場核對啟動項：**以 `startup` 帳號登入，按 `Win + R` 輸入 `shell:startup`（不要加 `%`），核對捷徑的目標程式、參數及「起始位置」。這是目前使用者的啟動資料夾；實際捷徑設定和啟動工作目錄尚待現場記錄。程式中的 `data/`、`logs/` 均使用相對路徑，備份或排障前先確認工作目錄，不能僅以 exe 所在位置或交接包根目錄推定。啟停後確認後端可連線、管理頁可登入，並檢查工作目錄下的 `logs/`。Windows 啟動資料夾指令見 [Microsoft 說明](https://support.microsoft.com/en-gb/windows/experience/startup-boot/configure-startup-applications-in-windows?nochrome=true)。

## 人工備份與還原

目前**沒有自動備份**。後端工作目錄下的 `data/punch_hot.db` 是熱資料庫；`data/archives/punch_<年份>.db` 是可能存在的年度歸檔庫。應一起保存現有資料庫檔；年度歸檔程式雖已實作，但目前未見自動呼叫或排程，不可假定每年都會產生歸檔檔案。熱資料庫包含帳號及裝置憑證，備份檔須限制存取。

1. 選擇停止打卡影響較小的時段，記錄桌面端與 ESP32 的待補送事件，並通知現場暫停打卡；待補送事件不會包含在此次後端備份內。
2. 確認後端實際工作目錄，停止後端程序；確認程序已結束，再將 `data/punch_hot.db` 與存在的 `data/archives/*.db` 複製到具日期標記、受限制的備份位置。不要在後端仍寫入時直接複製資料庫檔。
3. 記錄備份日期、來源工作目錄、檔案清單與大小；重新啟動後端，確認管理頁可登入並查得到近期紀錄，再恢復打卡。

**還原時：**先隔離需要保留的新打卡資料，停止後端，保留目前資料庫的額外副本，再把同一批備份的熱庫與歸檔庫放回原工作目錄；啟動後檢查管理頁、近期紀錄、裝置核准狀態，並核對停機期間各讀卡端的待補送事件。還原舊備份可能覆蓋備份後新增的紀錄及裝置資料，必須先確認差額與補登方式。不要把桌面端的 `data/offline_punches.json` 或 ESP32 LittleFS 佇列當作後端資料庫備份。

**交接待辦：**備份頻率、保存位置、保留期間、執行人與還原演練負責人均尚未訂定；啟動捷徑目標與工作目錄也待現場填寫。

## 裝置管理與排障

1. 新桌面端先於托盤選單設定伺服器 URL，例如 `http://192.168.100.23:16688`；裝置身分存在 Windows `%LOCALAPPDATA%\CVTAClockIn\device.json`，不可複製到另一台電腦。ESP32 依 GitHub 上的[設定指南](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/firmware/GUIDE.md)設定 Wi-Fi、伺服器、名稱及 UID 校對。
2. 管理員在「系統管理 → 讀卡端管理」核對裝置 UUID 後核准。待審、暫停、停用或撤銷的裝置不能打卡；撤銷後若需重新配對，依 GitHub 上的[部署與協定文件](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/docs/DEPLOYMENT_AND_PROTOCOL.md)處理。桌面端與 ESP32 約每 30 秒同步一次狀態。
3. 桌面端斷線打卡會寫入該端工作目錄的 `data/offline_punches.json`，恢復連線後以**相同裝置 UUID**補送；桌面端日誌位於 `%LOCALAPPDATA%\CVTAClockIn\logs\`。ESP32 先將事件存入 LittleFS，`OFFLINE SAVED` 表示尚待伺服器確認，可用 `queue`、`bad`、`status` 查狀態。處理 401／403 時先查核准狀態與時間同步，勿把拒絕當作已補送。
4. 管理頁無法開啟時，先查後端程序、監聽埠、包內 `api_server/_internal/dist/` 與工作目錄下的 `logs/`；能開頁卻無法打卡時，查裝置狀態、實體讀卡器或 ESP32 的 Wi-Fi／NTP，再核對打卡紀錄。細節見 GitHub 上的[部署與協定](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/docs/DEPLOYMENT_AND_PROTOCOL.md)及[韌體測試方法](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/firmware/TESTING.md)。

## 接手驗收

- 以 `startup` 帳號確認登入自啟、捷徑指向及工作目錄，並驗證管理頁、登入、讀卡端連線與一筆測試打卡。
- 現場演練核准新裝置、斷線暫存與恢復補送；ESP32 須完成 GitHub 上的[正式韌體現場驗收](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/firmware/TESTING.md#正式韌體現場驗收)。
- 執行一次人工備份與還原演練，確認熱庫和既有歸檔庫可讀，並補齊上列交接待辦。
