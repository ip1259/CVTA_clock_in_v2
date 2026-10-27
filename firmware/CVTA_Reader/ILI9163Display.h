#ifndef CVTA_ILI9163_DISPLAY_H
#define CVTA_ILI9163_DISPLAY_H

#include <Adafruit_GFX.h>
#include <Arduino.h>
#include <SPI.h>

// The original module responds to the ILI9163C initialization sequence. Its
// 128x128 visible area maps to controller RAM rows 32..159. Other batches may
// expose a different RAM origin; pass their measured offsets to the constructor.
// The TFT and RC522 share the ESP32 hardware SPI pins, with separate CS pins.
class ILI9163Display : public Adafruit_GFX {
 public:
  enum class Orientation : uint8_t {
    Normal = 0, FlipHorizontal = 1, FlipVertical = 2, Rotate180 = 3
  };

  ILI9163Display(uint8_t cs, uint8_t dc, uint8_t rst, uint8_t otherCs,
                 uint8_t columnOffset = 0, uint8_t rowOffset = 32,
                 Orientation orientation = Orientation::Normal)
      : Adafruit_GFX(128, 128), cs_(cs), dc_(dc), rst_(rst), otherCs_(otherCs),
        columnOffset_(columnOffset), rowOffset_(rowOffset),
        orientation_(orientation) {}

  void setOffsets(uint8_t columnOffset, uint8_t rowOffset) {
    columnOffset_ = columnOffset;
    rowOffset_ = rowOffset;
  }

  // Call after begin(). Orientation changes may require new panel offsets.
  void setOrientation(Orientation orientation) {
    orientation_ = orientation;
    commandData(0x36, 0x08 | (static_cast<uint8_t>(orientation_) << 6));
  }

  void begin() {
    pinMode(otherCs_, OUTPUT);
    pinMode(cs_, OUTPUT);
    pinMode(dc_, OUTPUT);
    pinMode(rst_, OUTPUT);
    digitalWrite(otherCs_, HIGH);
    digitalWrite(cs_, HIGH);
    digitalWrite(rst_, HIGH);
    delay(50);
    digitalWrite(rst_, LOW);
    delay(50);
    digitalWrite(rst_, HIGH);
    delay(150);
    command(0x01);  // SWRESET
    delay(150);
    command(0x11);  // SLPOUT
    delay(150);

    commandData(0x26, 0x04);       // gamma curve
    commandData(0xF2, 0x01);       // enable gamma adjustment
    commandData2(0xB1, 0x08, 0x02);  // frame rate
    commandData(0xB4, 0x07);       // inversion control
    commandData2(0xC0, 0x0A, 0x02);  // power control 1
    commandData(0xC1, 0x02);       // power control 2
    commandData2(0xC5, 0x50, 0x63);  // VCOM control
    commandData(0xC7, 0x00);       // VCOM offset
    commandData(0x3A, 0x05);       // RGB565
    setOrientation(orientation_);  // BGR order and panel direction
    command(0x20);                 // INVOFF
    command(0x13);                 // NORON
    delay(10);
    command(0x29);                 // DISPON
    delay(100);
  }

  void drawPixel(int16_t x, int16_t y, uint16_t color) override {
    fillRect(x, y, 1, 1, color);
  }

  void fillRect(int16_t x, int16_t y, int16_t w, int16_t h,
                uint16_t color) override {
    if (w <= 0 || h <= 0 || x >= 128 || y >= 128) return;
    int32_t x0 = x, y0 = y, x1 = x0 + w, y1 = y0 + h;
    if (x1 <= 0 || y1 <= 0) return;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > 128) x1 = 128;
    if (y1 > 128) y1 = 128;

    setWindow(x0, y0, x1 - 1, y1 - 1);
    SPI.beginTransaction(spiSettings_);
    digitalWrite(otherCs_, HIGH);
    digitalWrite(dc_, HIGH);
    digitalWrite(cs_, LOW);
    uint8_t chunk[512];
    for (size_t i = 0; i < sizeof(chunk); i += 2) {
      chunk[i] = color >> 8;
      chunk[i + 1] = color & 0xFF;
    }
    uint32_t pixels = static_cast<uint32_t>(x1 - x0) * (y1 - y0);
    while (pixels) {
      uint32_t batch = pixels > sizeof(chunk) / 2 ? sizeof(chunk) / 2 : pixels;
      SPI.writeBytes(chunk, batch * 2);
      pixels -= batch;
    }
    digitalWrite(cs_, HIGH);
    SPI.endTransaction();
  }

  void fillScreen(uint16_t color) override {
    fillRect(0, 0, 128, 128, color);
  }

  // Send a prepared RGB565 image as one continuous update. Used to avoid
  // clearing the visible status area before drawing replacement text.
  void pushRGB565(int16_t x, int16_t y, const uint16_t *pixels,
                  int16_t w, int16_t h) {
    if (!pixels || x < 0 || y < 0 || w <= 0 || h <= 0 ||
        x + w > 128 || y + h > 128) return;
    setWindow(x, y, x + w - 1, y + h - 1);
    SPI.beginTransaction(spiSettings_);
    digitalWrite(otherCs_, HIGH);
    digitalWrite(dc_, HIGH);
    digitalWrite(cs_, LOW);
    uint8_t chunk[512];
    uint32_t count = static_cast<uint32_t>(w) * h;
    uint32_t index = 0;
    while (index < count) {
      uint32_t batch = count - index;
      if (batch > sizeof(chunk) / 2) batch = sizeof(chunk) / 2;
      for (uint32_t i = 0; i < batch; ++i) {
        uint16_t color = pixels[index + i];
        chunk[2 * i] = color >> 8;
        chunk[2 * i + 1] = color & 0xFF;
      }
      SPI.writeBytes(chunk, batch * 2);
      index += batch;
    }
    digitalWrite(cs_, HIGH);
    SPI.endTransaction();
  }

 private:
  void setWindow(uint8_t x0, uint8_t y0, uint8_t x1, uint8_t y1) {
    uint16_t firstColumn = static_cast<uint16_t>(x0) + columnOffset_;
    uint16_t lastColumn = static_cast<uint16_t>(x1) + columnOffset_;
    uint16_t firstRow = static_cast<uint16_t>(y0) + rowOffset_;
    uint16_t lastRow = static_cast<uint16_t>(y1) + rowOffset_;
    command(0x2A);  // CASET
    data(firstColumn >> 8); data(firstColumn & 0xFF);
    data(lastColumn >> 8); data(lastColumn & 0xFF);
    command(0x2B);  // RASET
    data(firstRow >> 8); data(firstRow & 0xFF);
    data(lastRow >> 8); data(lastRow & 0xFF);
    command(0x2C);  // RAMWR
  }

  void sendByte(uint8_t value, bool isData) {
    SPI.beginTransaction(spiSettings_);
    digitalWrite(otherCs_, HIGH);
    digitalWrite(dc_, isData ? HIGH : LOW);
    digitalWrite(cs_, LOW);
    SPI.transfer(value);
    digitalWrite(cs_, HIGH);
    SPI.endTransaction();
  }

  void command(uint8_t value) { sendByte(value, false); }
  void data(uint8_t value) { sendByte(value, true); }
  void commandData(uint8_t cmd, uint8_t value) {
    command(cmd);
    data(value);
  }
  void commandData2(uint8_t cmd, uint8_t a, uint8_t b) {
    command(cmd);
    data(a);
    data(b);
  }

  const uint8_t cs_, dc_, rst_, otherCs_;
  uint8_t columnOffset_, rowOffset_;
  Orientation orientation_;
  SPISettings spiSettings_{20000000, MSBFIRST, SPI_MODE0};
};

#endif  // CVTA_ILI9163_DISPLAY_H
