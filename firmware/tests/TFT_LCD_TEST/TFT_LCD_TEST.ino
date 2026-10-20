#include <Arduino.h>
#include <SPI.h>
#include "ILI9163Display.h"
#include "ReaderStatusDisplay.h"

// Same connections and display driver as the production CVTA reader.
constexpr uint8_t RFID_SS_PIN = 25;
constexpr uint8_t TFT_CS_PIN = 26;
constexpr uint8_t TFT_DC_PIN = 21;
constexpr uint8_t TFT_RST_PIN = 22;

ILI9163Display tft(TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN, RFID_SS_PIN);
GFXcanvas16 clockCanvas(128, 76);
uint16_t shownBackground = 0x0000;
bool clockMode = false;
uint32_t lastClockUpdate = 0;
uint32_t clockSeconds = 0;
size_t demoIndex = 0;

struct DemoStatus {
  const char *status;
  const char *detail;
};

constexpr DemoStatus demos[] = {
    {"READY", "12:34:56"},
    {"SAVED", "12:34:56"},
    {"OK", "12:34:56"},
    {"OFFLINE SAVED", "12:34:56"},
    {"DENIED", "CHECK DEVICE"},
    {"STORAGE ERROR", ""},
    {"PENDING", "12:34:56"},
};

void showNextStatus() {
  clockMode = false;
  const DemoStatus &demo = demos[demoIndex];
  uint32_t start = micros();
  readerDrawStatus(tft, clockCanvas, demo.status, demo.detail,
                   shownBackground);
  Serial.printf("Status %s / %s rendered in %lu us\n", demo.status,
                demo.detail, static_cast<unsigned long>(micros() - start));
  demoIndex = (demoIndex + 1) % (sizeof(demos) / sizeof(demos[0]));
}

void showClockFrame() {
  if (!clockCanvas.getBuffer()) {
    Serial.println("Clock canvas allocation failed");
    clockMode = false;
    return;
  }
  char displayTime[9];
  snprintf(displayTime, sizeof(displayTime), "%02lu:%02lu:%02lu",
           static_cast<unsigned long>((clockSeconds / 3600) % 100),
           static_cast<unsigned long>((clockSeconds / 60) % 60),
           static_cast<unsigned long>(clockSeconds % 60));
  uint32_t start = micros();
  readerDrawStatus(tft, clockCanvas, "READY", displayTime,
                   shownBackground);
  Serial.printf("Clock %s transferred in %lu us\n", displayTime,
                static_cast<unsigned long>(micros() - start));
  ++clockSeconds;
}

void showPattern() {
  tft.fillScreen(0x0000);
  shownBackground = 0xFFFF;
  tft.drawRect(0, 0, 128, 128, 0xFFFF);
  tft.setTextWrap(false);
  tft.setTextSize(2);
  tft.setTextColor(0xFFFF);
  tft.setCursor(11, 14);
  tft.print("ESP32");
  tft.setTextSize(1);
  tft.setTextColor(0x07FF);
  tft.setCursor(13, 48);
  tft.print("ILI9163 TEST");
  tft.fillRect(9, 75, 30, 30, 0xF800);
  tft.fillRect(49, 75, 30, 30, 0x07E0);
  tft.fillRect(89, 75, 30, 30, 0x001F);
  Serial.println("Showing test pattern");
}

void showColor(uint16_t color, const char *name) {
  tft.fillScreen(color);
  shownBackground = 0xFFFF;
  Serial.print("Showing ");
  Serial.println(name);
}

void setup() {
  Serial.begin(115200);
  pinMode(RFID_SS_PIN, OUTPUT);
  digitalWrite(RFID_SS_PIN, HIGH);
  SPI.begin(18, -1, 23, TFT_CS_PIN);
  tft.begin();
  Serial.println("TFT: ILI9163-compatible init, 20 MHz buffered SPI, visible rows 32..159");
  Serial.println("Commands: s=next status/color demo, c=1 Hz clock, p=pattern, r/g/b/k/w=solid color");
  showPattern();
}

void loop() {
  if (Serial.available()) {
    switch (Serial.read()) {
      case 'c':
        clockMode = true;
        clockSeconds = 0;
        shownBackground = 0xFFFF;
        showClockFrame();
        lastClockUpdate = millis();
        break;
      case 's': showNextStatus(); break;
      case 'p': clockMode = false; showPattern(); break;
      case 'r': clockMode = false; showColor(0xF800, "RED"); break;
      case 'g': clockMode = false; showColor(0x07E0, "GREEN"); break;
      case 'b': clockMode = false; showColor(0x001F, "BLUE"); break;
      case 'k': clockMode = false; showColor(0x0000, "BLACK"); break;
      case 'w': clockMode = false; showColor(0xFFFF, "WHITE"); break;
      default: break;
    }
  }
  if (clockMode && millis() - lastClockUpdate >= 1000) {
    lastClockUpdate += 1000;
    showClockFrame();
  }
}
