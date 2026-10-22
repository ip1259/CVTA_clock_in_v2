# CVTA 打卡系統：讀卡端部署與裝置協定

## 升級與資料庫版本

熱資料庫 `data/punch_hot.db` 的原有結構為 schema 第 0 版。升級前先讓舊桌面端補送完 `data/offline_punches.json` 中的打卡資料，備份熱資料庫與該離線檔，再停止舊版後端與讀卡端。新版離線資料會綁定裝置 UUID，不會自動補送沒有 UUID 的舊資料。現行 schema 為第 3 版：後端啟動時將已知的第 0 版建立裝置表，將第 1 版加入一次性加卡及結果欄位，或將第 2 版加入加卡結果欄位；全新資料庫直接建立第 3 版。版本較新、結構不符或遷移失敗時後端停止啟動；不可用 `create_all` 掩蓋錯誤。年度歸檔庫不保存裝置憑證。

原本後台的「舊資料庫匯入」只用於匯入舊系統考勤資料，與自動 schema 升級不同。

打包伺服器前，先在 `frontend` 目錄執行 `npm run build`；`api_server.spec` 會將產生的根目錄 `dist` 一併打包。

## 設定與核准讀卡端

後端預設監聽 `0.0.0.0:16688`。跨機部署前應設定獨立的 `CVTA_ADMIN_SECRET_KEY`，並立即修改初始管理員 `admin` 的預設密碼。在受信任的內網中，開啟桌面讀卡端托盤選單的「設定伺服器位址」，填入後端的完整 URL，例如 `http://192.168.1.10:16688`。也可在首次啟動前設定 `CVTA_CLOCKIN_API_URL` 和 `CVTA_CLOCKIN_API_PORT`。讀卡端會產生 UUID 與 256 位元密鑰，保存於 Windows `%LOCALAPPDATA%\CVTAClockIn\device.json`；不得複製該檔到其他裝置，也不得寫入版本庫或日誌。

裝置會送出待審申請。管理員在「系統管理 → 讀卡端管理」核對托盤選單顯示的 UUID，命名並核准。未核准、暫停、停用或撤銷時，讀卡端不能打卡或新增卡片。撤銷不可復原；如需重新配對，刪除裝置上的憑證檔後重啟，並核准新 UUID。後台可暫停／恢復所有刷卡操作，以及要求程式重啟。連線正常時裝置約每 5 秒同步一次；ESP32 失敗時約 30 秒後重試，Windows 桌面端的網路失敗仍約每 5 秒重試，註冊或簽章驗證失敗則約 30 秒後重試。未送達的重啟或加卡指令會在 5 分鐘後過期。

目前沿用內網 HTTP。首次註冊時密鑰會透過內網傳送，請只在受信任的網路配對，限制後端資料庫與裝置設定檔的讀取權限。若需跨不受信任網路部署，應先啟用 HTTPS。HMAC 保護後續裝置請求和控制回應的完整性，但 HTTP 不提供內容保密。

## ESP32 相容的 HTTP 協定

NodeMCU-32S／RC522 獨立讀卡器的[韌體與接線](../firmware/GUIDE.md)及 [Build 指南](../firmware/BUILD.md)已提供。

ESP32 韌體及其他讀卡端皆依以下協定運作：

1. 首次產生標準小寫 UUID 與 32 位元組隨機密鑰，以小寫十六進位表示。`POST /api/v1/devices/register`，JSON 為 `{"uuid":"...","secret":"64 個十六進位字元","name":"..."}`。密鑰須持久保存。重送相同資料具冪等性；相同 UUID 配不同密鑰會回傳 409。
2. 對 `GET /api/v1/devices/me`、`POST /api/v1/punch`、`POST /api/v1/cards/empty`、`POST /api/v1/devices/me/commands/{id}/ack` 加上 `X-Device-Id`、`X-Device-Timestamp`（Unix 秒）、`X-Device-Nonce`（16 個隨機位元組的小寫 hex）和 `X-Device-Signature`。
3. 簽章為小寫 hex 的 `HMAC-SHA256(secret_bytes, METHOD + "\n" + raw_path_with_query + "\n" + timestamp + "\n" + nonce + "\n" + SHA256(raw_body).hexdigest())`。`METHOD` 大寫；空 body 仍計算 SHA-256。伺服器容許時鐘誤差 5 分鐘，nonce 10 分鐘內不可重用。ESP32 須先完成時間同步。
4. 裝置 API 回應帶 `X-Device-Response-Signature`，內容為 `HMAC-SHA256(secret_bytes, request_nonce + "\n" + HTTP_status + "\n" + SHA256(raw_response_body).hexdigest())`。執行控制指令或接受打卡結果前須驗證回應。管理頁登入使用管理員 JWT；裝置加卡請求不使用管理員 JWT。
5. 連線正常時約每 5 秒輪詢 `/api/v1/devices/me`；ESP32 失敗後約 30 秒重試，Windows 桌面端的網路失敗維持約 5 秒、註冊或簽章驗證失敗約 30 秒重試；ESP32 在 Wi‑Fi 重連或 NTP 校時完成後立即輪詢；Windows 桌面端若打卡請求先恢復成功，也會立即重新同步裝置狀態。桌面端離線打卡紀錄於程式啟動並同步成功、連線恢復或下一次打卡成功時立即嘗試補送，另保留每 5 分鐘的週期重試。`status=approved` 且 `paused=false` 才可刷卡。`restart` 指令須先向 ack API 回報，再重啟讀卡應用程式或韌體。打卡離線佇列須記錄來源 UUID，僅能以相同裝置身分補送；401／403 不得當成離線成功。

### 遠端新增空卡

管理員在「卡片管理」選已核准、未暫停的讀卡端，後端以 `POST /api/v1/devices/{uuid}/commands` 建立 `enroll_card` 命令。裝置在簽章驗證通過的 `/api/v1/devices/me` 回應中取得命令 `id` 與 `credential`（64 位十六進位字元），向 `/api/v1/devices/me/commands/{id}/ack` 回報且驗證其成功回應後，才進入 30 秒加卡模式。未送達的命令 5 分鐘後失效。

第一次刷卡送 `POST /api/v1/cards/empty`，JSON 為 `{"uid":"...","credential":"..."}`，並帶原有裝置 HMAC 簽章。後端只接受該裝置已確認、未過期、未使用的憑證；即使 UID 已存在，該憑證仍被耗用。裝置讀過第一張卡或逾時 30 秒即切回打卡模式，新增請求不進入離線打卡佇列，模式切換不等待加卡 API 結果；隨後讀卡端依已驗證簽章的回應顯示成功、卡號已存在或失敗，無法確認回應時明示結果未確認。後端在同一交易中記錄加卡結果；管理頁以管理員 JWT 查詢 `GET /api/v1/devices/{uuid}/commands/{id}`，回報 `pending_delivery`、`waiting_for_card`、`succeeded`、`duplicate` 或 `expired`，成功時自動更新卡片清單。網路錯誤時管理頁可重試查詢；憑證不會回傳給管理頁。憑證與裝置密鑰不得寫入日誌；現行 HTTP 僅適用受信任內網，HMAC 不提供傳輸保密。
