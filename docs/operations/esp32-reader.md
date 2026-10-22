# 設定 ESP32 獨立讀卡端

此讀卡端由 NodeMCU-32S、RC522 與 1.44 吋 TFT 組成，可不依賴 Windows 電腦持續運行；仍需電源、Wi-Fi、NTP 時間同步及後端核准。更換板子、讀卡器或顯示模組後，要重新檢查接線及卡號校對。詳細腳位與模組限制見[韌體與接線指南](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/firmware/GUIDE.md)。

## 首次設定

1. 依接線指南接好 RC522、TFT 與 3.3 V 電源；更換不同批次模組時先完成對應硬體測試。依[Build 指南](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/firmware/BUILD.md)燒錄正式韌體。
2. 以 **115200 baud** 開啟序列監控器，行尾選 **Newline**，輸入 `selftest`。應看到 `Protocol self-test PASS`。也可按韌體指南使用 BLE 終端完成設定。
3. 輸入 `wifi <SSID> <密碼>`、`server http://192.168.100.23:16688`、`name <設備名稱>`，再輸入 `status`。確認 Wi-Fi 與 NTP 時間同步成功；`server` 不加 API 路徑。序列埠輸入不會遮蔽 Wi-Fi 密碼，僅在可信任電腦操作。
4. 記下 `status` 顯示的 UUID。管理員在「系統管理 → 讀卡端管理」按「重新整理」，核對 UUID 並核准。輸入 `poll` 可立即查詢；連線正常時自動輪詢約每 5 秒一次，失敗時約 30 秒後重試。確認裝置已核准且未暫停。
5. 若沿用既有卡號，先查同一張實卡在舊讀卡器或後台的 UID，依指南執行 `calibrate <既有 UID>`，60 秒內刷該卡。只有顯示 `UID MATCH` 才開始正式打卡，不要因 `UID MISMATCH` 直接重綁所有卡。
6. 刷一張已綁定的卡，在管理頁查核入庫時間與員工；檢查 TFT 返回 READY，並以 `queue` 確認沒有未補送事件。

**完成標準：**`selftest` 通過、時間已同步、UUID 已核准、UID 校對成功且實卡紀錄可查。更換分割區或清除快閃記憶體前，先確認 `queue` 為零；清除會失去本機設定與身分，須重新核准。完整現場測試見[韌體驗收方法](https://github.com/ip1259/CVTA_clock_in_v2/blob/master/firmware/TESTING.md)。

## 新增空卡

管理員在「卡片管理 → 新增卡片」選擇這台已核准、未暫停的讀卡端，發送加卡命令。等待 TFT 顯示 `ADD CARD`，在 30 秒內刷一張卡；第一次刷卡或逾時後自動回到打卡模式。加卡刷卡不進入離線打卡佇列。TFT 會顯示 `CARD ADDED`、`CARD EXISTS`、`ADD FAILED`、`ADD UNKNOWN` 或 `ADD TIMEOUT`；最後一種表示無法確認伺服器回應，須在管理頁查詢結果。管理頁也會顯示加卡結果並在成功時更新卡片清單。ESP32 必須先用既有卡完成 UID 順序校對；斷線時加卡模式會結束，需重新下達命令。
