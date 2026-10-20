# TFT LCD 測試

此程式使用與正式 `CVTA_Reader` 相同的 ILI9163 相容顯示驅動，以 20 MHz 硬體 SPI 和區塊傳送顯示文字、外框和紅／綠／藍色塊。需安裝 **Adafruit GFX Library**；`ILI9163Display.h` 與 `ReaderStatusDisplay.h` 已隨測試程式附上，Arduino IDE 開啟 `.ino` 時應保持三個檔案在同一資料夾。

先拔除 RC522，TFT 的 `LED/VCC → 3V3`、`GND → GND`、`SCK → GPIO18`、`SDA → GPIO23`、`AO/A0 → GPIO21`、`RESET → GPIO22`、`CS → GPIO26`。在 Arduino IDE 選 NodeMCU-32S，燒錄 `TFT_LCD_TEST.ino`，序列監控器設 115200 baud。

開機後應看到白框、`ESP32`、`ILI9163 TEST` 及三個紅／綠／藍色塊。序列命令 `p` 重畫圖案，`r/g/b/k/w` 填滿紅／綠／藍／黑／白。若圖案缺邊或顏色異常，可用[控制器診斷測試](../TFT_CONTROLLER_TEST/README.md)重測控制器記憶體偏移與 SPI 模式。

送 `c` 可模擬正式韌體的每秒時間更新：先在記憶體畫好 `READY` 與時間，再一次送至顯示器。序列輸出每次區域傳送的微秒數。請觀察時間是否仍明顯閃爍；送 `p` 可退出時鐘模式。

送 `s` 可依序預覽正式韌體的狀態畫面：READY 黑底、SAVED／OK 綠底、OFFLINE SAVED 深琥珀底、DENIED／STORAGE ERROR 紅底、PENDING 黑底。每次送一次 `s` 切換下一個狀態；長狀態會分成兩行顯示。紅色錯誤畫面有白框，讓辨識不只依賴顏色。請確認每個畫面的字沒有被裁切，白色字在各背景上清楚，且換色後沒有殘留上一個畫面。

這塊實物的畫面與正式韌體觀察見[實測結果](../../TEST_RESULTS.md)。

若畫面正確但更新較慢，可用[更新速度測試](../TFT_REFRESH_TEST/README.md)量測不同 SPI 時鐘與區塊傳送的效果。
