# CVTA 打卡系統：讀卡端部署與裝置協定

## 升級與資料庫版本

熱資料庫 `data/punch_hot.db` 的原有結構為 schema 第 0 版。升級前先讓舊桌面端補送完 `data/offline_punches.json` 中的打卡資料，備份熱資料庫與該離線檔，再停止舊版後端與讀卡端。新版離線資料會綁定裝置 UUID，不會自動補送沒有 UUID 的舊資料。啟動新版後端時，程序檢查舊版表結構，成功後建立裝置表並將 SQLite `PRAGMA user_version` 設為 1。全新資料庫直接建立第 1 版。版本較新、結構不符或遷移失敗時後端停止啟動；不可用 `create_all` 掩蓋錯誤。年度歸檔庫不保存裝置憑證。

原本後台的「舊資料庫匯入」只用於匯入舊系統考勤資料，與自動 schema 升級不同。

打包伺服器前，先在 `frontend` 目錄執行 `npm run build`；`api_server.spec` 會將產生的根目錄 `dist` 一併打包。

## 設定與核准讀卡端

後端預設監聽 `0.0.0.0:16688`。跨機部署前應設定獨立的 `CVTA_ADMIN_SECRET_KEY`，並立即修改初始管理員 `admin` 的預設密碼。在受信任的內網中，開啟桌面讀卡端托盤選單的「設定伺服器位址」，填入後端的完整 URL，例如 `http://192.168.1.10:16688`。也可在首次啟動前設定 `CVTA_CLOCKIN_API_URL` 和 `CVTA_CLOCKIN_API_PORT`。讀卡端會產生 UUID 與 256 位元密鑰，保存於 Windows `%LOCALAPPDATA%\CVTAClockIn\device.json`；不得複製該檔到其他裝置，也不得寫入版本庫或日誌。

裝置會送出待審申請。管理員在「系統管理 → 讀卡端管理」核對托盤選單顯示的 UUID，命名並核准。未核准、停用或撤銷時，讀卡端不能打卡或新增卡片。撤銷不可復原；如需重新配對，刪除裝置上的憑證檔後重啟，並核准新 UUID。後台可暫停／恢復所有刷卡操作，以及要求程式重啟。在線裝置約每 30 秒同步一次；未送達的重啟指令會在 5 分鐘後過期，避免裝置久後上線時意外重啟。

目前沿用內網 HTTP。首次註冊時密鑰會透過內網傳送，請只在受信任的網路配對，限制後端資料庫與裝置設定檔的讀取權限。若需跨不受信任網路部署，應先啟用 HTTPS。HMAC 保護後續裝置請求和控制回應的完整性，但 HTTP 不提供內容保密。

## ESP32 相容的 HTTP 協定

本版尚未提供 ESP32 韌體；任何讀卡端可依以下協定實作：

1. 首次產生標準小寫 UUID 與 32 位元組隨機密鑰，以小寫十六進位表示。`POST /api/v1/devices/register`，JSON 為 `{"uuid":"...","secret":"64 個十六進位字元","name":"..."}`。密鑰須持久保存。重送相同資料具冪等性；相同 UUID 配不同密鑰會回傳 409。
2. 對 `GET /api/v1/devices/me`、`POST /api/v1/punch`、`POST /api/v1/cards/empty`、`POST /api/v1/devices/me/commands/{id}/ack` 加上 `X-Device-Id`、`X-Device-Timestamp`（Unix 秒）、`X-Device-Nonce`（16 個隨機位元組的小寫 hex）和 `X-Device-Signature`。
3. 簽章為小寫 hex 的 `HMAC-SHA256(secret_bytes, METHOD + "\n" + raw_path_with_query + "\n" + timestamp + "\n" + nonce + "\n" + SHA256(raw_body).hexdigest())`。`METHOD` 大寫；空 body 仍計算 SHA-256。伺服器容許時鐘誤差 5 分鐘，nonce 10 分鐘內不可重用。ESP32 須先完成時間同步。
4. 裝置 API 回應帶 `X-Device-Response-Signature`，內容為 `HMAC-SHA256(secret_bytes, request_nonce + "\n" + HTTP_status + "\n" + SHA256(raw_response_body).hexdigest())`。執行控制指令或接受打卡結果前須驗證回應。登入仍使用既有管理員 JWT；新增空卡同時需要該 JWT 與裝置簽章。
5. 約每 30 秒輪詢 `/api/v1/devices/me`。`status=approved` 且 `paused=false` 才可刷卡。`restart` 指令須先向 ack API 回報，再重啟讀卡應用程式或韌體。打卡離線佇列須記錄來源 UUID，僅能以相同裝置身分補送；401／403 不得當成離線成功。
