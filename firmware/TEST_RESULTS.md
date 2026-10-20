# 讀卡端實測結果

以下是目前這塊 NodeMCU-32S、RC522 與 1.44 吋 SPI TFT 實物的測試紀錄。更換模組批次、板型或接線後應重新驗證；這些結果不能單獨證明 LCD 控制器型號。

## TFT 控制器與接線

- TFT VCC 對 GND 約 3.31 V。曾在 TFT SCK 腳量到約 0.2 V，但 ESP32 GPIO18 在 `Probe HIGH` 時約 3.3 V；接線修正後，SCK、SDA、AO、RESET、CS 五個訊號腳都能在測試模式切換高低電位。
- 使用 `TFT_CONTROLLER_TEST` 送 `i` 後能顯示全紅，送 `k` 後能顯示全黑。送 `p` 時，由上至下看見綠、藍、黃、洋紅色帶，對應控制器記憶體第 32–159 列為可視區。
- 1 MHz 硬體 SPI 的 `h` 模式能顯示全紅，隨後 `k` 能顯示全黑。實物適用 ILI9163C 相容初始化與第 32 列偏移；賣場雖標示 ST7735，單靠上述現象仍不能確定晶片型號。

## TFT 傳輸速度與畫面

單獨接 TFT 的 `TFT_REFRESH_TEST` 在 40 MHz 要求時鐘下，畫面圖案與外圍換色均正常：

| 傳送模式 | 全畫面 `full` | 區域 `partial` | 全畫面傳輸速度換算 |
| --- | ---: | ---: | ---: |
| 逐位元組 | 30,439 µs | 18,131 µs | 32.9 次／秒 |
| 512 位元組區塊 | 7,616 µs | 4,594 µs | 131.3 次／秒 |

以上是**資料傳輸**耗時，不是 LCD 面板掃描刷新率。正式韌體使用 20 MHz 區塊傳送。

- `TFT_LCD_TEST` 的每秒 READY 時鐘更新不再明顯閃爍。
- 狀態展示 `s` 依序顯示黑、綠、深琥珀、紅底時，文字清楚完整，換色後沒有殘影。
- 正式韌體接回 RC522 後，畫面與連續刷卡正常；成功時綠底，約 3 秒後返回黑底 READY。

## BLE 與儲存空間

- 原 NodeMCU-32S 預設 1.25 MB APP 分割區編譯含 BLE 的韌體時出現 `text section exceeds available space in board`。改用同一塊實體板、Arduino IDE 的 ESP32 Dev Module 與 Huge APP（3 MB APP／約 1 MB SPIFFS）後，Verify／Upload 成功；BLE 裝置名稱和 TFT 六位配對碼均出現。
- BLE 配對後，`help` 與 `status` 均能回覆；終端以 LF 或 CRLF 作行尾都能執行。先前一次 `Unknown command` 後確認是測試輸入問題，沒有為此修改指令解析。
- 切換分割區前舊佇列為 0 筆。切換後第一次刷卡顯示 `QUEUE FULL/ERR`，執行 `init-storage NEW` 初始化新 LittleFS 分割區並重啟後，刷卡正常。後續原始碼已改成未掛載時顯示 `STORAGE ERROR`；這項提示修改尚未單獨實機驗證。

## RC522 測試範圍

正式韌體已確認可連續刷卡，且 BLE 連線與新分割區初始化後也可刷卡。`RFID_READ` 獨立測試程式提供卡號、卡片類型與 RC522 版本輸出，但目前沒有另行記錄這支測試程式的實測數值。
