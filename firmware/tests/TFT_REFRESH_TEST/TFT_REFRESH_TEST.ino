#include <Arduino.h>
#include <SPI.h>

// This benchmark uses the proven ILI9163-compatible init and row offset 32.
// Disconnect RC522 while finding the display's reliable SPI clock.
constexpr uint8_t TFT_SCK = 18;
constexpr uint8_t TFT_MOSI = 23;
constexpr uint8_t TFT_CS = 26;
constexpr uint8_t TFT_DC = 21;
constexpr uint8_t TFT_RST = 22;
constexpr uint8_t RFID_SS = 25;

constexpr uint32_t frequencies[] = {
    1000000, 2000000, 4000000, 8000000, 12000000,
    16000000, 20000000, 26000000, 40000000};
constexpr size_t frequencyCount = sizeof(frequencies) / sizeof(frequencies[0]);
size_t frequencyIndex = 0;
bool buffered = false;
bool magentaBackground = true;

SPISettings settings() {
  return SPISettings(frequencies[frequencyIndex], MSBFIRST, SPI_MODE0);
}

void byteToDisplay(uint8_t value, bool isData) {
  SPI.beginTransaction(settings());
  digitalWrite(RFID_SS, HIGH);
  digitalWrite(TFT_DC, isData ? HIGH : LOW);
  digitalWrite(TFT_CS, LOW);
  SPI.transfer(value);
  digitalWrite(TFT_CS, HIGH);
  SPI.endTransaction();
}

void command(uint8_t value) { byteToDisplay(value, false); }
void data(uint8_t value) { byteToDisplay(value, true); }
void commandData(uint8_t cmd, uint8_t value) {
  command(cmd);
  data(value);
}
void commandData2(uint8_t cmd, uint8_t a, uint8_t b) {
  command(cmd);
  data(a);
  data(b);
}

void initialize() {
  // Initialization is always sent at the known-good 1 MHz setting.
  size_t selected = frequencyIndex;
  frequencyIndex = 0;
  digitalWrite(TFT_CS, HIGH);
  digitalWrite(TFT_RST, HIGH);
  delay(50);
  digitalWrite(TFT_RST, LOW);
  delay(50);
  digitalWrite(TFT_RST, HIGH);
  delay(150);
  command(0x01); delay(150);  // software reset
  command(0x11); delay(150);  // sleep out
  commandData(0x26, 0x04);
  commandData(0xF2, 0x01);
  commandData2(0xB1, 0x08, 0x02);
  commandData(0xB4, 0x07);
  commandData2(0xC0, 0x0A, 0x02);
  commandData(0xC1, 0x02);
  commandData2(0xC5, 0x50, 0x63);
  commandData(0xC7, 0x00);
  commandData(0x3A, 0x05);
  commandData(0x36, 0x08);
  command(0x20);
  command(0x13);
  delay(10);
  command(0x29);
  delay(100);
  frequencyIndex = selected;
}

void fillRect(int16_t x, int16_t y, int16_t w, int16_t h, uint16_t color) {
  if (x < 0 || y < 0 || w <= 0 || h <= 0 || x + w > 128 || y + h > 128) return;
  uint16_t firstRow = y + 32;
  uint16_t lastRow = y + h - 1 + 32;
  command(0x2A);
  data(0); data(x); data(0); data(x + w - 1);
  command(0x2B);
  data(firstRow >> 8); data(firstRow & 0xFF);
  data(lastRow >> 8); data(lastRow & 0xFF);
  command(0x2C);

  SPI.beginTransaction(settings());
  digitalWrite(RFID_SS, HIGH);
  digitalWrite(TFT_DC, HIGH);
  digitalWrite(TFT_CS, LOW);
  uint32_t pixels = static_cast<uint32_t>(w) * h;
  if (buffered) {
    uint8_t chunk[512];
    for (size_t i = 0; i < sizeof(chunk); i += 2) {
      chunk[i] = color >> 8;
      chunk[i + 1] = color & 0xFF;
    }
    while (pixels) {
      uint32_t batch = pixels > sizeof(chunk) / 2 ? sizeof(chunk) / 2 : pixels;
      SPI.writeBytes(chunk, batch * 2);
      pixels -= batch;
    }
  } else {
    while (pixels--) {
      SPI.transfer(color >> 8);
      SPI.transfer(color & 0xFF);
    }
  }
  digitalWrite(TFT_CS, HIGH);
  SPI.endTransaction();
}

void benchmark() {
  // Measure transfer and command overhead, excluding Serial output.
  magentaBackground = !magentaBackground;
  uint16_t background = magentaBackground ? 0xF81F : 0x0000;
  uint32_t start = micros();
  fillRect(0, 0, 128, 128, background);
  uint32_t fullUs = micros() - start;

  start = micros();
  fillRect(0, 28, 128, 76, 0xFFFF);
  uint32_t partialUs = micros() - start;

  // Easy-to-check final pattern: white band, four solid color squares.
  fillRect(8, 36, 52, 28, 0xF800);   // upper left: red
  fillRect(68, 36, 52, 28, 0x07E0);  // upper right: green
  fillRect(8, 68, 52, 28, 0x001F);   // lower left: blue
  fillRect(68, 68, 52, 28, 0x0000);  // lower right: black

  Serial.printf("SPI requested=%lu Hz, mode=%s, full=%lu us (%.1f transfer fps), partial=%lu us\n",
                static_cast<unsigned long>(frequencies[frequencyIndex]),
                buffered ? "buffered" : "byte-by-byte",
                static_cast<unsigned long>(fullUs),
                fullUs ? 1000000.0 / fullUs : 0.0,
                static_cast<unsigned long>(partialUs));
  Serial.printf("Check: %s outer margin; white band; red/green on top, blue/black below.\n",
                magentaBackground ? "MAGENTA" : "BLACK");
  Serial.println("Transfer fps is not the panel scan rate.");
}

void setup() {
  Serial.begin(115200);
  pinMode(RFID_SS, OUTPUT);
  pinMode(TFT_CS, OUTPUT);
  pinMode(TFT_DC, OUTPUT);
  pinMode(TFT_RST, OUTPUT);
  digitalWrite(RFID_SS, HIGH);
  digitalWrite(TFT_CS, HIGH);
  SPI.begin(TFT_SCK, -1, TFT_MOSI, TFT_CS);
  delay(300);
  Serial.println("TFT refresh benchmark: RC522 disconnected, 115200 baud.");
  Serial.println("n=next clock, b=previous clock, f=toggle buffered write, t=repeat, 1=reset at 1 MHz.");
  Serial.println("Only use a clock after checking its final pattern is complete and stable.");
  initialize();
  benchmark();
}

void loop() {
  if (!Serial.available()) return;
  switch (Serial.read()) {
    case 'n':
      if (frequencyIndex + 1 < frequencyCount) ++frequencyIndex;
      benchmark();
      break;
    case 'b':
      if (frequencyIndex > 0) --frequencyIndex;
      benchmark();
      break;
    case 'f':
      buffered = !buffered;
      benchmark();
      break;
    case 't': benchmark(); break;
    case '1':
      frequencyIndex = 0;
      initialize();
      benchmark();
      break;
    default: break;
  }
}
