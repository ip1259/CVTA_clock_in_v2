#ifndef CVTA_READER_STATUS_DISPLAY_H
#define CVTA_READER_STATUS_DISPLAY_H

#include <Adafruit_GFX.h>
#include <Arduino.h>
#include "ILI9163Display.h"

struct ReaderStatusPalette {
  uint16_t background;
  uint16_t title;
  uint16_t detail;
  bool error;
};

inline ReaderStatusPalette readerStatusPalette(const String &status) {
  // All colored RGB565 fills keep white text above 4.5:1 contrast.
  if (status == "OK" || status == "UID MATCH" || status == "CARD ADDED") {
    return {0x03A0, 0xFFFF, 0xFFFF, false};  // green: final confirmed success
  }
  if (status == "SAVED") {
    return {0x8B40, 0xFFFF, 0xFFFF, false};  // warm yellow: local step done, server pending
  }
  if (status == "OFFLINE SAVED" || status == "OFFLINE" || status == "PENDING" ||
      status == "TIME UNSYNC" || status == "SET NETWORK" ||
      status == "SET UID ORDER" || status == "CARD EXISTS" ||
      status == "ADD UNKNOWN" || status == "ADD TIMEOUT" ||
      status == "CAL TIMEOUT") {
    return {0xA180, 0xFFFF, 0xFFFF, false};  // orange: warning/action needed
  }
  if (status == "READY") {
    return {0x0000, 0xFFFF, 0x07FF, false};  // black, cyan clock
  }
  if (status == "CVTA READER" || status == "BLE PAIR" || status == "ADD CARD" ||
      status == "TAP KNOWN CARD" || status == "RESTARTING") {
    return {0x0000, 0xFFFF, 0xFFFF, false};  // neutral
  }
  return {0xA800, 0xFFFF, 0xFFFF, true};    // red: blocking/error state
}

inline void readerDrawCentered(Adafruit_GFX &surface, const String &text,
                              uint8_t scale, int16_t y, uint16_t color) {
  int16_t width = static_cast<int16_t>(text.length()) * 6 * scale;
  int16_t x = (128 - width) / 2;
  if (x < 0) x = 0;
  surface.setTextColor(color);
  surface.setTextSize(scale);
  surface.setCursor(x, y);
  surface.print(text);
}

inline void readerSplitText(const String &text, String &first, String &second) {
  first = text;
  second = "";
  if (text.length() <= 10) return;
  int split = -1;
  for (int i = 10; i > 0; --i) {
    if (text[i] == ' ') { split = i; break; }
  }
  if (split < 0) split = 10;
  first = text.substring(0, split);
  second = text.substring(split + (text[split] == ' ' ? 1 : 0));
}

inline void readerDrawStatus(ILI9163Display &display, GFXcanvas16 &canvas,
                             const String &status, const String &detail,
                             uint16_t &shownBackground) {
  ReaderStatusPalette palette = readerStatusPalette(status);
  bool buffered = canvas.getBuffer() != nullptr;
  Adafruit_GFX &surface = buffered ? static_cast<Adafruit_GFX &>(canvas)
                                   : static_cast<Adafruit_GFX &>(display);
  if (buffered) canvas.fillScreen(palette.background);
  else if (palette.background != shownBackground) display.fillScreen(palette.background);
  else display.fillRect(0, 28, 128, 76, palette.background);
  surface.setTextWrap(false);
  int16_t origin = buffered ? 0 : 28;

  String title1, title2, detail1, detail2;
  readerSplitText(status, title1, title2);
  readerSplitText(detail, detail1, detail2);

  if (title2.length()) {
    readerDrawCentered(surface, title1, 2, origin + 2, palette.title);
    readerDrawCentered(surface, title2, 2, origin + 22, palette.title);
    if (detail.length()) {
      uint8_t scale = detail2.length() ? 1 : 2;
      readerDrawCentered(surface, detail, scale, origin + 52, palette.detail);
    }
  } else {
    uint8_t titleScale = title1.length() <= 6 ? 3 : 2;
    int16_t titleY = detail.length() ? 8 : (titleScale == 3 ? 24 : 28);
    readerDrawCentered(surface, title1, titleScale, origin + titleY,
                       palette.title);
    if (detail2.length()) {
      readerDrawCentered(surface, detail1, 2, origin + 40, palette.detail);
      readerDrawCentered(surface, detail2, 2, origin + 59, palette.detail);
    } else if (detail.length()) {
      readerDrawCentered(surface, detail1, 2, origin + 48, palette.detail);
    }
  }

  if (palette.error) surface.drawRect(0, origin, 128, 76, 0xFFFF);
  if (buffered) {
    display.pushRGB565(0, 28, canvas.getBuffer(), 128, 76);
    if (palette.background != shownBackground) {
      display.fillRect(0, 0, 128, 28, palette.background);
      display.fillRect(0, 104, 128, 24, palette.background);
    }
  }
  shownBackground = palette.background;
}

#endif  // CVTA_READER_STATUS_DISPLAY_H
