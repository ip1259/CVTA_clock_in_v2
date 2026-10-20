# TFT 控制器診斷

此測試先使用低速軟體 SPI，分別送出 ST7735 與 ILI9163C 的初始化命令，也可切換 1 MHz 硬體 SPI。只需 ESP32 Arduino 核心，不需安裝額外顯示函式庫。這是診斷程式；賣場仍標示本模組為 ST7735，不能只憑 PCB 外觀判定為 ILI9163C。

先拔除 RC522，保持 TFT 原接線。模組背面排針順序為 `LED、SCK、SDA、AO、RESET、CS、GND、VCC`：`LED/VCC → 3V3`、`GND → GND`、`SCK → GPIO18`、`SDA → GPIO23`、`AO → GPIO21`、`RESET → GPIO22`、`CS → GPIO26`。

在 Arduino IDE 開啟 `TFT_CONTROLLER_TEST.ino`，開發板選 NodeMCU-32S。序列監控器設為 115200 baud。啟動後先以 ST7735 初始化並填紅；等序列出現 `Fill complete: RED` 再看畫面。送 `i` 改以 ILI9163C 初始化並填紅，送 `s` 切回 ST7735。送 `r/g/b/k/w` 分別填紅、綠、藍、黑、白；每次都等 `Fill complete` 後判斷。填滿可能需數秒。

送 `p` 顯示色帶位置；送 `h` 可切換 1 MHz 硬體 SPI，送 `t` 可切回低速軟體 SPI。這塊實物的實際觀察見[實測結果](../../TEST_RESULTS.md)。

若只有 `i` 有反應，模組可能使用 ILI9163C 或相容控制器，需再核對實物後才修改正式韌體。若 `s`、`i` 都維持相同橫條紋，且 `k` 無效，仍無法認定控制器型號；下一步應用邏輯分析儀量測模組端的 SCK、SDA、AO、CS、RESET 動態波形，或以已知正常的模組交叉測試。萬用表的高低電位測試只能確認靜態連通性。

參考：[賣場規格](https://shop.cpu.com.tw/product/56857/info/)、[ILI9163C 控制器函式庫初始化序列](https://github.com/sumotoy/TFT_ILI9163C/blob/master/TFT_ILI9163C.cpp)、[Adafruit ST7735 函式庫](https://github.com/adafruit/Adafruit-ST7735-Library)。
