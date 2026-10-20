#include <Arduino.h>
#include <SPI.h>

// Standalone, slow 4-wire SPI diagnostic. No display library is required.
// TFT header: LED, SCK, SDA, AO, RESET, CS, GND, VCC.
constexpr uint8_t SCK_PIN = 18;
constexpr uint8_t SDA_PIN = 23;
constexpr uint8_t DC_PIN = 21;  // AO / A0 on the module
constexpr uint8_t RST_PIN = 22;
constexpr uint8_t CS_PIN = 26;
constexpr uint8_t RFID_SS_PIN = 25;

constexpr uint8_t SWRESET = 0x01;
constexpr uint8_t SLPOUT = 0x11;
constexpr uint8_t NORON = 0x13;
constexpr uint8_t INVOFF = 0x20;
constexpr uint8_t DISPON = 0x29;
constexpr uint8_t CASET = 0x2A;
constexpr uint8_t RASET = 0x2B;
constexpr uint8_t RAMWR = 0x2C;
constexpr uint8_t MADCTL = 0x36;
constexpr uint8_t COLMOD = 0x3A;

enum class Controller : uint8_t { ST7735, ILI9163C };
Controller controller = Controller::ST7735;
bool hardwareSpi = false;
SPISettings slowSpi(1000000, MSBFIRST, SPI_MODE0);

void beginTransfer() {
  if (hardwareSpi) SPI.beginTransaction(slowSpi);
  digitalWrite(CS_PIN, LOW);
}

void endTransfer() {
  digitalWrite(CS_PIN, HIGH);
  if (hardwareSpi) SPI.endTransaction();
}

// SPI mode 0: data is stable before the rising clock edge. The deliberate
// microsecond pauses make this much slower than the display library's SPI.
void writeByte(uint8_t value) {
  if (hardwareSpi) {
    SPI.transfer(value);
    return;
  }
  for (uint8_t mask = 0x80; mask != 0; mask >>= 1) {
    digitalWrite(SCK_PIN, LOW);
    digitalWrite(SDA_PIN, (value & mask) ? HIGH : LOW);
    delayMicroseconds(2);
    digitalWrite(SCK_PIN, HIGH);
    delayMicroseconds(2);
  }
  digitalWrite(SCK_PIN, LOW);
}

void command(uint8_t value) {
  beginTransfer();
  digitalWrite(DC_PIN, LOW);
  writeByte(value);
  endTransfer();
}

void data(uint8_t value) {
  beginTransfer();
  digitalWrite(DC_PIN, HIGH);
  writeByte(value);
  endTransfer();
}

void command2(uint8_t cmd, uint8_t a, uint8_t b) {
  command(cmd);
  data(a);
  data(b);
}

void resetDisplay() {
  digitalWrite(CS_PIN, HIGH);
  if (!hardwareSpi) digitalWrite(SCK_PIN, LOW);
  digitalWrite(RST_PIN, HIGH);
  delay(50);
  digitalWrite(RST_PIN, LOW);
  delay(50);
  digitalWrite(RST_PIN, HIGH);
  delay(150);
  command(SWRESET);
  delay(150);
  command(SLPOUT);
  delay(150);
}

void initialize(Controller selected) {
  controller = selected;
  resetDisplay();

  if (controller == Controller::ILI9163C) {
    // ILI9163C-specific register values, based on the controller library's
    // initialization sequence. These make a genuine driver difference from ST.
    command(0x26); data(0x04);              // gamma curve
    command(0xF2); data(0x01);              // enable gamma adjustment
    command2(0xB1, 0x08, 0x02);             // frame rate
    command(0xB4); data(0x07);              // inversion control
    command2(0xC0, 0x0A, 0x02);             // power control 1
    command(0xC1); data(0x02);              // power control 2
    command2(0xC5, 0x50, 0x63);             // VCOM control
    command(0xC7); data(0x00);              // VCOM offset
  } else {
    command2(0xB1, 0x01, 0x2C);             // ST7735 frame rate
    command2(0xB2, 0x01, 0x2C);
    command(0xB4); data(0x07);
    command(0xC0); data(0xA2); data(0x02); data(0x84);
    command(0xC1); data(0xC5);
    command2(0xC5, 0x0A, 0x00);
  }

  command(COLMOD); data(0x05);              // RGB565, 16 bits/pixel
  command(MADCTL); data(0x08);              // BGR order, no rotation
  command(INVOFF);
  command(NORON);
  delay(10);
  command(DISPON);
  delay(100);
  Serial.println(controller == Controller::ST7735
                     ? "ST7735 init sent" : "ILI9163C init sent");
}

void fill(uint16_t color, const char *name) {
  // Write the entire 128x160 controller RAM. A 128x128 glass can have a
  // vertical offset; this covers both zero-offset and 32-row-offset panels.
  command(CASET);
  data(0); data(0); data(0); data(127);
  command(RASET);
  data(0); data(0); data(0); data(159);
  command(RAMWR);
  beginTransfer();
  digitalWrite(DC_PIN, HIGH);
  for (uint32_t pixel = 0; pixel < 128UL * 160UL; ++pixel) {
    writeByte(color >> 8);
    writeByte(color & 0xFF);
  }
  endTransfer();
  Serial.print("Fill complete: ");
  Serial.println(name);
}

void showBands() {
  // The glass shows 128 of the controller's 160 rows. Five 32-row bands
  // reveal whether its visible area starts near row 0 or row 32.
  constexpr uint16_t colors[] = {0xF800, 0x07E0, 0x001F, 0xFFE0, 0xF81F};
  command(CASET);
  data(0); data(0); data(0); data(127);
  command(RASET);
  data(0); data(0); data(0); data(159);
  command(RAMWR);
  beginTransfer();
  digitalWrite(DC_PIN, HIGH);
  for (uint16_t row = 0; row < 160; ++row) {
    uint16_t color = colors[row / 32];
    for (uint16_t column = 0; column < 128; ++column) {
      writeByte(color >> 8);
      writeByte(color & 0xFF);
    }
  }
  endTransfer();
  Serial.println("Bands complete: RAM rows 0-31 RED, 32-63 GREEN, 64-95 BLUE, 96-127 YELLOW, 128-159 MAGENTA");
}

void setup() {
  Serial.begin(115200);
  pinMode(RFID_SS_PIN, OUTPUT);
  digitalWrite(RFID_SS_PIN, HIGH);
  pinMode(SCK_PIN, OUTPUT);
  pinMode(SDA_PIN, OUTPUT);
  pinMode(DC_PIN, OUTPUT);
  pinMode(RST_PIN, OUTPUT);
  pinMode(CS_PIN, OUTPUT);
  digitalWrite(CS_PIN, HIGH);
  digitalWrite(SCK_PIN, LOW);
  delay(300);
  Serial.println("TFT controller diagnostic; RC522 should be disconnected.");
  Serial.println("s=ST7735, i=ILI9163C; r/g/b/k/w=solid color; p=bands; h=hardware SPI 1 MHz; t=software SPI.");
  Serial.println("Serial output only confirms transmission, not TFT response.");
  initialize(Controller::ST7735);
  fill(0xF800, "RED");
}

void loop() {
  if (!Serial.available()) return;
  switch (Serial.read()) {
    case 's': initialize(Controller::ST7735); fill(0xF800, "RED"); break;
    case 'i': initialize(Controller::ILI9163C); fill(0xF800, "RED"); break;
    case 'r': fill(0xF800, "RED"); break;
    case 'g': fill(0x07E0, "GREEN"); break;
    case 'b': fill(0x001F, "BLUE"); break;
    case 'k': fill(0x0000, "BLACK"); break;
    case 'w': fill(0xFFFF, "WHITE"); break;
    case 'p': showBands(); break;
    case 'h':
      if (!hardwareSpi) {
        SPI.begin(SCK_PIN, -1, SDA_PIN, CS_PIN);
        hardwareSpi = true;
      }
      initialize(Controller::ILI9163C);
      fill(0xF800, "RED via hardware SPI");
      break;
    case 't':
      if (hardwareSpi) {
        SPI.end();
        hardwareSpi = false;
        pinMode(SCK_PIN, OUTPUT);
        pinMode(SDA_PIN, OUTPUT);
        digitalWrite(SCK_PIN, LOW);
      }
      initialize(Controller::ILI9163C);
      fill(0xF800, "RED via software SPI");
      break;
    default: break;
  }
}
