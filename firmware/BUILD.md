# CVTA Reader Build 與燒錄指南

本指南使用 Arduino IDE 2 編譯並燒錄 [`CVTA_Reader.ino`](CVTA_Reader/CVTA_Reader.ino)。接線及序列埠設定見[接線與操作](GUIDE.md)，刷卡驗收見[測試方法](TESTING.md)。

## 1. 準備開發環境

Arduino IDE 安裝與新增 ESP32 開發板的步驟，請參考傑森創工的[〈在 Arduino IDE 中新增 ESP32 的開發板：以 NodeMCU-32S 為例〉](https://blog.jmaker.com.tw/arduino-ide-esp32/)。完成後，使用具資料傳輸功能的 USB 線連接開發板；TFT、RC522 與電容接線見[硬體說明](GUIDE.md#材料與接線)。

## 2. 選擇板子與分割區

1. 在原 Arduino IDE 2 的 **Library Manager** 安裝 **MFRC522 by GithubCommunity**、**ArduinoJson by Benoit Blanchon**（7.x）與 **Adafruit GFX Library**；依提示安裝其相依函式庫。BLE 使用 **esp32 by Espressif Systems** 板套件內附的 BLE 函式庫，無須另裝同名第三方 BLE 函式庫。ILI9163 相容顯示驅動已放在 `CVTA_Reader/ILI9163Display.h`，不需安裝另一個顯示控制器函式庫。板型、燒錄流程與原開發環境相同。
2. 以 **File → Open** 開啟 `firmware/CVTA_Reader/CVTA_Reader.ino`。保留 `.ino` 與同名 `CVTA_Reader` 資料夾的關係。
   若更換 LCD 且畫面顛倒或位移，先用[畫面測試](tests/TFT_LCD_TEST/DETAILS.md#更換模組後校正畫面位置)測得方向和偏移值。正式韌體可用 `m`、`o` 指令調整並保存；檔案開頭的 `TFT_ORIENTATION`、`TFT_COLUMN_OFFSET` 與 `TFT_ROW_OFFSET` 只決定尚無儲存設定時的預設值。目前蝦皮購入、實物 PCB 絲印 V1.1 的模組預設為 `Rotate180`、`(2, 3)`；原廣華購入、實物 PCB 絲印 V2 的模組實測值為 `Normal`、`(0, 32)`。
3. 使用原本的 **NodeMCU-32S 實體開發板**，但在 **Tools → Board** 選 **ESP32 Dev Module**；**Flash Mode 選 DIO**、Flash Size 選 **4 MB**，Port 與上傳速度保持原設定。BLE 加入後，`NodeMCU-32S` 板型固定的 1.25 MB APP 分割區可能不足；`ESP32 Dev Module` 可選較大的分割區，GPIO 接線不變。
4. 在 **Tools → Partition Scheme** 選 **Huge APP (3MB No OTA/1MB SPIFFS)**。此配置仍有名為 `spiffs` 的資料分割區供 LittleFS 保存離線佇列。此韌體沒有 OTA 更新流程。若選項名稱略有不同，確認為 3 MB APP、保留約 1 MB SPIFFS 的配置；**不要選沒有 SPIFFS 的配置**。
5. 其餘上傳選項先保留板型預設值。若上傳不穩，再降低 **Upload Speed**。

**從原本 NodeMCU-32S 預設分割區切換前**，先讓舊韌體連線補送，並在序列埠執行 `queue`，確認 `Stored events: 0`。新分割區的 LittleFS 起點不同，舊位置的待補送事件不會自動搬移；若有 `.bad` 事件，也先用 `bad` 記下內容並完成處理。不要勾選 **Erase All Flash**；官方 Huge APP 與原預設配置的 NVS 位置相同，正常燒錄應保留裝置 UUID、密鑰及 Wi‑Fi 設定。切換後第一次掛載若顯示 `STORAGE ERROR`，只在已確認舊佇列為空時執行一次 `init-storage NEW`，再重新開機確認。之後更新韌體請保持 **ESP32 Dev Module／Huge APP** 配置。

## 3. 編譯與上傳

1. 點選左上角 **Verify**（✓）進行編譯。確認輸出視窗顯示編譯完成，且沒有 `error:`。
2. 點選 **Upload**（→）編譯並燒錄。完成後等待板子重新啟動。若一直停在連線階段，依板子需求按住 **BOOT** 直到開始寫入，再放開。
3. 開啟 **Serial Monitor**，設為 **115200 baud**，行尾設為 **Newline**。輸入 `selftest`，確認輸出 `Protocol self-test PASS`。
4. 輸入 `status`，確認能看到完整裝置 UUID，且沒有 `CONFIG ERROR`、`CRYPTO ERROR`。首次使用若出現 `STORAGE ERROR`，只在確認裝置沒有既有離線資料時執行 `init-storage NEW`。以最後輸出的 `Storage initialized.` 判定初始化成功；首次掛載前可能先出現 `Corrupted dir pair`／`mount failed (-84)`，這是空白分割區尚未格式化時的訊息。
5. 依[設定與啟用](GUIDE.md#設定與啟用)透過 USB 或 BLE 輸入 `wifi`、`server`、`name`，待後台核准，再用 `calibrate` 校對既有卡號。BLE 使用方法見[BLE 設定連線](GUIDE.md#ble-設定連線)。

**Verify 只編譯；Upload 才會寫入板子。**Arduino 的[官方上傳指南](https://docs.arduino.cc/software/ide-v2/tutorials/getting-started/ide-v2-uploading-a-sketch/)也說明這兩個操作。

若要保存此次編譯產物，可使用 **Sketch → Export Compiled Binary**，再以 **Sketch → Show Sketch Folder** 找到輸出的檔案。保留同次建置的板型、分割區與函式庫版本紀錄；日後仍以 IDE 的 **Upload** 流程燒錄，避免只拿單一 `.bin` 檔卻漏掉所需的分割區或開機配置。[Arduino 平台規格](https://docs.arduino.cc/arduino-cli/platform-specification/)

## 4. 常見問題

| 現象 | 檢查項目 |
| --- | --- |
| `ArduinoJson.h` 或 `MFRC522.h` 找不到 | 在 Library Manager 安裝上述函式庫，並重新啟動 IDE。 |
| 找不到 `WiFi.h`、`LittleFS.h` 或 `esp_sntp.h` | 確認已安裝 **esp32 by Espressif Systems**，且選的是 ESP32 板型。 |
| `mbedtls_sha256_ret` 未宣告 | 確認使用目前版本的 `CVTA_Reader.ino`；韌體已改用 `mbedtls_md()`。 |
| 找不到序列埠 | 換資料 USB 線、檢查 USB 轉序列埠驅動與 Windows 裝置管理員。 |
| 上傳卡在 Connecting | 確認 Port 正確；必要時按住 BOOT，或降低 Upload Speed。 |
| `STORAGE ERROR` | 全新裝置可執行一次 `init-storage NEW`。若結尾是 `Storage initialized.`，代表已成功，即使前面有掛載錯誤訊息；重新啟動後應能正常掛載。若結尾仍是 `Storage initialization failed.`，保留完整序列輸出排查。既有裝置不可反覆格式化，以免遺失待補送資料。 |
| `TIME UNSYNC` | 確認 Wi‑Fi 與 NTP 可用；每次開機都須成功校時後才能打卡。 |
| TFT 無顯示或出現橫條紋 | 依[接線表](GUIDE.md#材料與接線)檢查 3.3 V、GND、背光、SCK／MOSI、GPIO26 片選、GPIO21 DC、GPIO22 RES；核對實物排針標示。先跑[TFT LCD 測試](tests/TFT_LCD_TEST/DETAILS.md)；若仍異常，使用[控制器診斷測試](tests/TFT_CONTROLLER_TEST/DETAILS.md)確認初始化、記憶體偏移與硬體 SPI。 |

在複製建置環境前，記下實測通過的 Arduino IDE、esp32 板套件、MFRC522、ArduinoJson 與 Adafruit GFX 函式庫版本，以及 Board、Upload Speed 選項；若所選板型提供 Partition Scheme，也記下該選項。其他電腦使用相同組合，可減少版本差異造成的編譯問題。
