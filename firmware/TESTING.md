# 讀卡端測試方法

各獨立測試程式的操作方式：

- [RC522 讀取測試](tests/RFID_READ/DETAILS.md)
- [TFT 控制器診斷](tests/TFT_CONTROLLER_TEST/DETAILS.md)
- [TFT LCD 畫面測試](tests/TFT_LCD_TEST/DETAILS.md)
- [TFT 更新速度測試](tests/TFT_REFRESH_TEST/DETAILS.md)

已完成的觀察與數值集中於[實測結果](TEST_RESULTS.md)。

## 正式韌體現場驗收

1. 以舊讀卡器與 RC522 刷同一張既有卡，校對 UID 後確認無須重新綁卡即可打卡；長時間貼卡只產生一筆，移開後可再次刷卡。
2. 分別驗證待審、核准、暫停／恢復、停用、撤銷，以及後台重啟指令。
3. 斷 Wi‑Fi 後刷卡，確認 `OFFLINE SAVED` 且 `queue` 增加；重啟後先恢復 NTP，再確認補送與佇列清空。測試佇列滿和 `.bad` 事件。
4. 在開機後尚未校時，以及最後校時超過 24 小時的條件下確認拒絕收卡。用 `selftest` 驗證簽章向量，並以正常後端往返驗證回應簽章。
5. 修改 Wi‑Fi 與伺服器 URL、重新開機，確認設定仍在；確認 TFT 在成功、斷網、拒絕、時間失效及儲存錯誤時給出對應訊息。檢查 TFT 與 RC522 共用 SPI 時能連續刷卡、畫面更新正常，並量測刷卡瞬間 RC522 端的 3.3 V 供電。
6. 以 BLE 終端連線並用 TFT 配對碼完成配對；訂閱 TX，行尾設為 LF 或 CRLF，輸入框分別只打 `help`、`status`，確認文字回覆。再以 BLE 修改一項可還原的設定，重新開機確認已保存；同時刷卡，確認 BLE 連線時 RC522 與 TFT 仍正常。
