#include <Arduino.h>
#include <MFRC522.h>
#include <SPI.h>

// Same RC522 wiring as firmware/CVTA_Reader/CVTA_Reader.ino.
constexpr uint8_t RFID_SCK = 18;
constexpr uint8_t RFID_MISO = 19;
constexpr uint8_t RFID_MOSI = 23;
constexpr uint8_t RFID_SS = 25;
constexpr uint8_t RFID_RST = 27;

// Keep the TFT off the shared SPI bus when it is connected.
constexpr uint8_t TFT_CS = 26;

MFRC522 rfid(RFID_SS, RFID_RST);

void printUid(const MFRC522::Uid &uid) {
  for (byte i = 0; i < uid.size; ++i) {
    if (uid.uidByte[i] < 0x10) Serial.print('0');
    Serial.print(uid.uidByte[i], HEX);
  }
}

void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(RFID_SS, OUTPUT);
  pinMode(TFT_CS, OUTPUT);
  digitalWrite(RFID_SS, HIGH);
  digitalWrite(TFT_CS, HIGH);
  SPI.begin(RFID_SCK, RFID_MISO, RFID_MOSI);
  rfid.PCD_Init();
  delay(4);

  Serial.println("RC522 read test");
  byte version = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  Serial.printf("RC522 VersionReg: 0x%02X\n", version);
  if (version == 0x00 || version == 0xFF) {
    Serial.println("Reader not detected. Check 3.3V, GND, SPI, SS and RST.");
  } else {
    Serial.println("Tap a 13.56 MHz card to read its UID.");
  }
}

void loop() {
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    delay(50);
    return;
  }

  Serial.print("UID: ");
  printUid(rfid.uid);
  Serial.printf(" (%u bytes)\n", static_cast<unsigned>(rfid.uid.size));
  MFRC522::PICC_Type type = rfid.PICC_GetType(rfid.uid.sak);
  Serial.print("Card type: ");
  Serial.println(rfid.PICC_GetTypeName(type));

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  delay(250);
}
