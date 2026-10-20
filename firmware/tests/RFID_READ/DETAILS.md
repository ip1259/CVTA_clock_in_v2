# RC522 讀取測試

使用原 NodeMCU-32S 開發板與 Arduino IDE，開啟同資料夾的 `RFID_READ.ino`。只需安裝主韌體已使用的 **MFRC522** 函式庫；測試不會連接 Wi-Fi、寫入裝置設定或存取打卡伺服器。

| RC522 | NodeMCU-32S |
| --- | --- |
| 3.3V | 3V3 |
| GND | GND |
| SCK | GPIO18 |
| MISO | GPIO19 |
| MOSI | GPIO23 |
| SDA／SS | GPIO25 |
| RST | GPIO27 |
| IRQ | 不接 |

若 TFT 同時接在共用 SPI 匯流排，程式會把 TFT 的 GPIO26 片選維持為高電位。RC522 端的 100 µF 電解電容與 0.1 µF 陶瓷電容仍依[硬體接線說明](../../GUIDE.md#材料與接線)並聯於 3.3V 和 GND；電解電容注意極性。

選 **NodeMCU-32S** 板型後燒錄，開啟 **115200 baud** 序列監控器。啟動時會印出 `VersionReg`；若為 `0x00` 或 `0xFF`，先檢查供電和接線。拿 13.56 MHz 卡靠近 RC522，預期輸出大寫十六進位 UID、UID 位元組數與卡片類型。移開卡片再靠近，可讀取下一次。此測試顯示 RC522 原始 UID，不進行正式韌體的 UID 順序校對或打卡。
