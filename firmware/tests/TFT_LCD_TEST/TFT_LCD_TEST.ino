#include <Arduino.h>
#include <SPI.h>
#include <stdio.h>
#include "ILI9163Display.h"
#include "ReaderStatusDisplay.h"

// Same connections and display driver as the production CVTA reader.
constexpr uint8_t RFID_SS_PIN = 25;
constexpr uint8_t TFT_CS_PIN = 26;
constexpr uint8_t TFT_DC_PIN = 21;
constexpr uint8_t TFT_RST_PIN = 22;
constexpr uint8_t DEFAULT_COLUMN_OFFSET = 0;
constexpr uint8_t DEFAULT_ROW_OFFSET = 32;

ILI9163Display tft(TFT_CS_PIN, TFT_DC_PIN, TFT_RST_PIN, RFID_SS_PIN,
                   DEFAULT_COLUMN_OFFSET, DEFAULT_ROW_OFFSET);
GFXcanvas16 clockCanvas(128, 76);
uint16_t shownBackground = 0x0000;
uint8_t columnOffset = DEFAULT_COLUMN_OFFSET;
uint8_t rowOffset = DEFAULT_ROW_OFFSET;
uint8_t orientationMode = 0;
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
    {"CARD ADDED", "A1B2C3D4"},
    {"CARD EXISTS", "A1B2C3D4"},
    {"ADD UNKNOWN", "CHECK ADMIN"},
    {"PUNCH ERROR", "404"},
    {"DENIED", "CHECK DEVICE"},
    {"STORAGE ERROR", ""},
    {"PENDING", "12:34:56"},
    {"TIME UNSYNC", ""},
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
  // Four distinct corners make clipping and direction of displacement visible.
  tft.fillRect(1, 1, 7, 7, 0xF800);
  tft.fillRect(120, 1, 7, 7, 0x07E0);
  tft.fillRect(1, 120, 7, 7, 0x001F);
  tft.fillRect(120, 120, 7, 7, 0xFFE0);
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

void setTestOffsets() {
  String input = Serial.readStringUntil('\n');
  int column, row;
  char extra;
  if (sscanf(input.c_str(), " %d %d %c", &column, &row, &extra) != 2 ||
      column < 0 || column > 128 || row < 0 || row > 128) {
    Serial.println("Use: o <column 0..128> <row 0..128> (example: o 0 0)");
    return;
  }
  clockMode = false;
  tft.fillScreen(0x0000);
  columnOffset = static_cast<uint8_t>(column);
  rowOffset = static_cast<uint8_t>(row);
  tft.setOffsets(columnOffset, rowOffset);
  Serial.printf("Testing column offset %u, row offset %u\n",
                static_cast<unsigned>(columnOffset), static_cast<unsigned>(rowOffset));
  showPattern();
}

void setTestOrientation() {
  String input = Serial.readStringUntil('\n');
  int mode;
  char extra;
  if (sscanf(input.c_str(), " %d %c", &mode, &extra) != 1 ||
      mode < 0 || mode > 3) {
    Serial.println("Use: m <0..3> (0=normal, 1=horizontal flip, 2=vertical flip, 3=180 degrees)");
    return;
  }
  clockMode = false;
  tft.fillScreen(0x0000);
  orientationMode = static_cast<uint8_t>(mode);
  tft.setOrientation(static_cast<ILI9163Display::Orientation>(orientationMode));
  Serial.printf("Testing orientation %u with offsets (%u, %u)\n",
                static_cast<unsigned>(orientationMode),
                static_cast<unsigned>(columnOffset), static_cast<unsigned>(rowOffset));
  showPattern();
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
  Serial.printf("TFT: ILI9163-compatible init, 20 MHz buffered SPI, initial offsets (%u, %u)\n",
                static_cast<unsigned>(columnOffset), static_cast<unsigned>(rowOffset));
  Serial.println("Commands: m <0..3>=orientation, o <column> <row>=offsets, s=status, c=clock, p=pattern, r/g/b/k/w=color");
  showPattern();
}

void loop() {
  if (Serial.available()) {
    switch (Serial.read()) {
      case 'm': setTestOrientation(); break;
      case 'o': setTestOffsets(); break;
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
