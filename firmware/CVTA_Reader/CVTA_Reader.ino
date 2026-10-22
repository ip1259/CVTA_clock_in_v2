#include <Arduino.h>
#include <ArduinoJson.h>
#include <Adafruit_GFX.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <BLESecurity.h>
#include "ILI9163Display.h"
#include "ReaderStatusDisplay.h"
#include <HTTPClient.h>
#include <LittleFS.h>
#include <MFRC522.h>
#include <Preferences.h>
#include <SPI.h>
#include <WiFi.h>
#include <esp_sntp.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <mbedtls/md.h>
#include <time.h>
#include <esp_arduino_version.h>

// NodeMCU-32S / generic ESP32. The RC522 IRQ pin is unused.
constexpr uint8_t RFID_SCK = 18;
constexpr uint8_t RFID_MISO = 19;
constexpr uint8_t RFID_MOSI = 23;
constexpr uint8_t RFID_SS = 25;
constexpr uint8_t RFID_RST = 27;
constexpr uint8_t TFT_CS = 26;
constexpr uint8_t TFT_DC = 21;
constexpr uint8_t TFT_RST = 22;
constexpr size_t QUEUE_LIMIT = 256;
constexpr uint32_t STATE_POLL_MS = 5000;
constexpr uint32_t STATE_RETRY_MS = 30000;
constexpr uint32_t RETRY_MS = 10000;
constexpr int64_t MAX_TIME_AGE_US = 24LL * 60 * 60 * 1000000;

Preferences settings;
MFRC522 rfid(RFID_SS, RFID_RST);
ILI9163Display tft(TFT_CS, TFT_DC, TFT_RST, RFID_SS);
GFXcanvas16 statusCanvas(128, 76);
uint16_t shownBackground = 0x0000;
String wifiSsid, wifiPassword, serverUrl, deviceName, deviceUuid, deviceSecret;
String serialLine, expectedUid, statusText, statusDetail;
String enrollmentCredential;
bool filesystemReady = false;
bool settingsReady = false;
bool cryptoReady = false;
bool ntpConfigured = false;
bool registered = false;
bool approved = false;
bool paused = false;
bool authBlocked = false;
bool cardLatched = false;
bool calibrationPending = false;
bool previousWifiConnected = false;
bool previousTimeReady = false;
uint8_t uidOrder = 0; // 0 = unset, 1 = RC522 order, 2 = reversed bytes
uint32_t nextQueueId = 1;
uint32_t lastPoll = 0;
uint32_t pollInterval = STATE_POLL_MS;
uint32_t lastRetry = 0;
uint32_t lastWifiAttempt = 0;
uint32_t cardAbsentSince = 0;
uint32_t calibrationStarted = 0;
uint32_t lastClockRefresh = 0;
uint32_t statusShownAt = 0;
uint32_t enrollmentStarted = 0;
portMUX_TYPE timeMux = portMUX_INITIALIZER_UNLOCKED;
volatile int64_t lastNtpUptimeUs = 0;

// Nordic UART Service: a line of text written to RX is one existing command.
constexpr char BLE_SERVICE_UUID[] = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E";
constexpr char BLE_RX_UUID[] = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E";
constexpr char BLE_TX_UUID[] = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E";
struct BleCommandLine { char text[221]; uint32_t session; };
QueueHandle_t bleCommands = nullptr;
BLECharacteristic *bleTx = nullptr;
volatile bool bleConnected = false;
volatile bool blePairingFinished = false;
volatile uint32_t blePairingPin = 0;
volatile uint32_t bleSession = 0;
volatile bool bleInputError = false;
volatile bool bleAuthenticated = false;
bool blePinOnScreen = false;
uint32_t blePin = 0;

class ReaderBleSecurity : public BLESecurityCallbacks {
 public:
  uint32_t onPassKeyRequest() override { return blePin; }
  void onPassKeyNotify(uint32_t pin) override { blePairingPin = pin; }
  bool onSecurityRequest() override { return true; }
  bool onConfirmPIN(uint32_t) override { return false; } // No confirm button on this reader.
  void onAuthenticationComplete(esp_ble_auth_cmpl_t result) override {
    bleAuthenticated = result.success;
    blePairingFinished = true;
  }
};

class ReaderBleServer : public BLEServerCallbacks {
 public:
  void onConnect(BLEServer *) override {
    ++bleSession;
    bleConnected = true;
    bleAuthenticated = false;
    blePairingFinished = false;
    blePairingPin = blePin;
  }
  void onDisconnect(BLEServer *server) override {
    bleConnected = false;
    bleAuthenticated = false;
    blePairingFinished = true;
    blePairingPin = 0;
    ++bleSession;
    server->startAdvertising();
  }
};

class ReaderBleRx : public BLECharacteristicCallbacks {
  BleCommandLine line_ = {};
  size_t length_ = 0;
  bool overflow_ = false;
  uint32_t session_ = 0;
 public:
  void onWrite(BLECharacteristic *characteristic) override {
    if (session_ != bleSession) {
      session_ = bleSession;
      length_ = 0;
      overflow_ = false;
    }
    auto value = characteristic->getValue();
    for (size_t i = 0; i < value.length(); ++i) {
      char c = value[i];
      if (c == '\r') continue;
      if (c == '\n') {
        if (!overflow_ && length_ && bleCommands) {
          line_.text[length_] = '\0';
          line_.session = bleSession;
          if (xQueueSend(bleCommands, &line_, 0) != pdTRUE) bleInputError = true;
        }
        if (overflow_) bleInputError = true;
        length_ = 0;
        overflow_ = false;
      } else if (length_ < sizeof(line_.text) - 1 && !overflow_) {
        line_.text[length_++] = c;
      } else {
        overflow_ = true; // Never execute a truncated command.
      }
    }
  }
};

class ReaderBleReply : public Print {
  uint8_t chunk_[20];
  size_t used_ = 0;
 public:
  size_t write(uint8_t c) override {
    chunk_[used_++] = c;
    if (used_ == sizeof(chunk_) || c == '\n') flush();
    return 1;
  }
  void flush() override {
    if (!used_ || !bleConnected || !bleTx) { used_ = 0; return; }
    bleTx->setValue(chunk_, used_);
    bleTx->notify();
    used_ = 0;
    delay(10); // Keep 20-byte notifications in order at the default MTU.
  }
};

void bleNotifyLine(const String &message) {
  if (!bleConnected || !bleAuthenticated) return;
  ReaderBleReply out;
  out.println(message);
  out.flush();
}

void setupBle() {
  bleCommands = xQueueCreate(4, sizeof(BleCommandLine));
  if (!bleCommands) { Serial.println("BLE command queue unavailable"); return; }
  blePin = 100000 + esp_random() % 900000;
  String bleName = String("CVTA-Reader");
  BLEDevice::init(bleName.c_str());
  BLESecurity *security = new BLESecurity();
#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 3, 1)
  security->setPassKey(true, blePin);
#else
  security->setStaticPIN(blePin);
#endif
  security->setAuthenticationMode(ESP_LE_AUTH_REQ_SC_MITM_BOND);
  security->setCapability(ESP_IO_CAP_OUT);
  BLEDevice::setSecurityCallbacks(new ReaderBleSecurity());
  BLEServer *server = BLEDevice::createServer();
  server->setCallbacks(new ReaderBleServer());
  BLEService *service = server->createService(BLE_SERVICE_UUID);
  bleTx = service->createCharacteristic(BLE_TX_UUID,
                                        BLECharacteristic::PROPERTY_READ |
                                        BLECharacteristic::PROPERTY_NOTIFY);
  bleTx->setAccessPermissions(ESP_GATT_PERM_READ_ENC_MITM);
  BLE2902 *notifySettings = new BLE2902();
  notifySettings->setAccessPermissions(ESP_GATT_PERM_READ_ENC_MITM |
                                       ESP_GATT_PERM_WRITE_ENC_MITM);
  bleTx->addDescriptor(notifySettings);
  BLECharacteristic *rx = service->createCharacteristic(BLE_RX_UUID,
                                         BLECharacteristic::PROPERTY_WRITE);
  rx->setAccessPermissions(ESP_GATT_PERM_WRITE_ENC_MITM);
  rx->setCallbacks(new ReaderBleRx());
  service->start();
  BLEAdvertising *advertising = server->getAdvertising();
  advertising->addServiceUUID(BLE_SERVICE_UUID);
  advertising->setScanResponse(true);
  advertising->start();
  Serial.print("BLE UART advertising as "); Serial.println(bleName);
}

struct ApiReply {
  int code = -1;
  bool verified = false;
  String body;
};

String toHex(const uint8_t *bytes, size_t length, bool upper = false) {
  const char *digits = upper ? "0123456789ABCDEF" : "0123456789abcdef";
  String result;
  result.reserve(length * 2);
  for (size_t i = 0; i < length; ++i) {
    result += digits[bytes[i] >> 4];
    result += digits[bytes[i] & 15];
  }
  return result;
}

bool decodeHex(const String &hex, uint8_t *bytes, size_t count) {
  if (hex.length() != count * 2) return false;
  for (size_t i = 0; i < count; ++i) {
    char a = hex[2 * i], b = hex[2 * i + 1];
    auto nibble = [](char c) -> int {
      if (c >= '0' && c <= '9') return c - '0';
      if (c >= 'a' && c <= 'f') return c - 'a' + 10;
      if (c >= 'A' && c <= 'F') return c - 'A' + 10;
      return -1;
    };
    int hi = nibble(a), lo = nibble(b);
    if (hi < 0 || lo < 0) return false;
    bytes[i] = (hi << 4) | lo;
  }
  return true;
}

String sha256Hex(const String &data) {
  uint8_t hash[32];
  const mbedtls_md_info_t *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (!info || mbedtls_md(info, reinterpret_cast<const uint8_t *>(data.c_str()),
                           data.length(), hash) != 0) return "";
  return toHex(hash, sizeof(hash));
}

String hmacHexWithKey(const String &secret, const String &message) {
  uint8_t key[32], output[32];
  if (!decodeHex(secret, key, sizeof(key))) return "";
  const mbedtls_md_info_t *info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (!info || mbedtls_md_hmac(info, key, sizeof(key),
      reinterpret_cast<const uint8_t *>(message.c_str()), message.length(), output) != 0) return "";
  return toHex(output, sizeof(output));
}

String hmacHex(const String &message) {
  return hmacHexWithKey(deviceSecret, message);
}

bool protocolSelfTest() {
  const String secret = String("abababababababababababababababab") +
                        "abababababababababababababababab";
  const String nonce = "0123456789abcdef0123456789abcdef";
  const String requestBody = "{\"uid\":\"123\"}";
  String request = "POST\n/api/v1/punch\n1792100000\n" + nonce + "\n" + sha256Hex(requestBody);
  String response = nonce + "\n200\n" + sha256Hex("{}");
  return hmacHexWithKey(secret, request) ==
             "0d397c519dd5ab424b4c0084194cc4c57263e860b7ecd041ad49f79c613b82f8" &&
         hmacHexWithKey(secret, response) ==
             "59794679dc9421862cf62c0f2d2adb1d5423bdc9a7d9484ae94c9f5740963dd8";
}

bool constantTimeEqual(const String &a, const String &b) {
  if (a.length() != 64 || b.length() != 64) return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < 64; ++i) difference |= a[i] ^ b[i];
  return difference == 0;
}

void tftShow(const String &top, const String &bottom) {
  readerDrawStatus(tft, statusCanvas, top, bottom, shownBackground);
}

void showStatus(const String &top, const String &bottom = "") {
  statusText = top;
  statusDetail = bottom;
  statusShownAt = millis();
  tftShow(top, bottom);
  Serial.print("[status] ");
  Serial.print(top);
  if (bottom.length()) { Serial.print(" "); Serial.print(bottom); }
  Serial.println();
  bleNotifyLine(String("[status] ") + top + (bottom.length() ? String(" ") + bottom : String("")));
}

void setupTft() {
  tft.begin();
  tft.fillScreen(0x0000);
  Serial.println("ILI9163-compatible TFT initialized (20 MHz SPI, row offset 32)");
  if (!statusCanvas.getBuffer()) {
    Serial.println("TFT status buffer unavailable; drawing directly");
  }
}

void onNtpSync(struct timeval *) {
  portENTER_CRITICAL(&timeMux);
  lastNtpUptimeUs = esp_timer_get_time();
  portEXIT_CRITICAL(&timeMux);
}

bool timeReady() {
  portENTER_CRITICAL(&timeMux);
  int64_t syncedAt = lastNtpUptimeUs;
  portEXIT_CRITICAL(&timeMux);
  return syncedAt > 0 && esp_timer_get_time() - syncedAt < MAX_TIME_AGE_US;
}

String localTimestamp() {
  time_t current = time(nullptr);
  struct tm local;
  if (!localtime_r(&current, &local)) return "";
  char buffer[20];
  strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &local);
  return String(buffer);
}

String currentClock() {
  String stamp = localTimestamp();
  return stamp.length() == 19 ? stamp.substring(11, 19) : "--:--:--";
}

String newUuid() {
  uint8_t bytes[16];
  esp_fill_random(bytes, sizeof(bytes));
  bytes[6] = (bytes[6] & 0x0F) | 0x40;
  bytes[8] = (bytes[8] & 0x3F) | 0x80;
  String raw = toHex(bytes, sizeof(bytes));
  return raw.substring(0, 8) + "-" + raw.substring(8, 12) + "-" + raw.substring(12, 16) +
         "-" + raw.substring(16, 20) + "-" + raw.substring(20);
}

void loadSettings() {
  if (!settings.begin("cvta-reader", false)) {
    showStatus("CONFIG ERROR");
    return;
  }
  settingsReady = true;
  wifiSsid = settings.getString("ssid", "");
  wifiPassword = settings.getString("pass", "");
  serverUrl = settings.getString("server", "");
  deviceName = settings.getString("name", "ESP32 Reader");
  deviceUuid = settings.getString("uuid", "");
  deviceSecret = settings.getString("secret", "");
  uidOrder = settings.getUChar("uid-order", 0);
  approved = settings.getBool("approved", false);
  paused = settings.getBool("paused", false);
  registered = settings.getBool("registered", false);
  if (deviceUuid.length() != 36 || deviceSecret.length() != 64) {
    uint8_t secret[32];
    esp_fill_random(secret, sizeof(secret));
    deviceUuid = newUuid();
    deviceSecret = toHex(secret, sizeof(secret));
    approved = false;
    paused = false;
    registered = false;
    settings.putString("uuid", deviceUuid);
    settings.putString("secret", deviceSecret);
    settings.putBool("approved", false);
    settings.putBool("registered", false);
  }
}

bool validServerUrl(String url) {
  if (!url.startsWith("http://") || url.length() < 10 || url.indexOf(' ') >= 0 ||
      url.indexOf('@') >= 0 || url.indexOf('?') >= 0 || url.indexOf('#') >= 0) return false;
  String authority = url.substring(7);
  return authority.length() > 0 && authority.indexOf('/') < 0;
}

void connectWifi() {
  if (wifiSsid.isEmpty()) return;
  lastWifiAttempt = millis();
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());
  Serial.println("Connecting Wi-Fi...");
}

void maintainWifi() {
  bool connected = WiFi.status() == WL_CONNECTED;
  if (!connected) ntpConfigured = false;
  if (connected && !ntpConfigured) {
    configTime(8 * 3600, 0, "pool.ntp.org", "time.google.com");
    ntpConfigured = true;
  }
  if (!connected && wifiSsid.length() && millis() - lastWifiAttempt >= 15000) {
    connectWifi();
  }
}

ApiReply signedRequest(const String &method, const String &path, const String &body = "") {
  ApiReply reply;
  if (!cryptoReady || WiFi.status() != WL_CONNECTED || !timeReady() || !validServerUrl(serverUrl)) return reply;
  uint8_t randomNonce[16];
  esp_fill_random(randomNonce, sizeof(randomNonce));
  String nonce = toHex(randomNonce, sizeof(randomNonce));
  char timestampBuffer[24];
  snprintf(timestampBuffer, sizeof(timestampBuffer), "%lld", static_cast<long long>(time(nullptr)));
  String timestamp(timestampBuffer);
  String canonical = method + "\n" + path + "\n" + timestamp + "\n" + nonce + "\n" + sha256Hex(body);
  String signature = hmacHex(canonical);
  if (signature.length() != 64) return reply;

  WiFiClient transport;
  HTTPClient http;
  http.setTimeout(4000);
  if (!http.begin(transport, serverUrl + path)) return reply;
  const char *responseHeaders[] = {"X-Device-Response-Signature"};
  http.collectHeaders(responseHeaders, 1);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Id", deviceUuid);
  http.addHeader("X-Device-Timestamp", timestamp);
  http.addHeader("X-Device-Nonce", nonce);
  http.addHeader("X-Device-Signature", signature);
  reply.code = method == "GET" ? http.GET() : http.POST(body);
  if (reply.code > 0) {
    reply.body = http.getString();
    String expected = hmacHex(nonce + "\n" + String(reply.code) + "\n" + sha256Hex(reply.body));
    reply.verified = constantTimeEqual(http.header("X-Device-Response-Signature"), expected);
  }
  http.end();
  return reply;
}

bool registerDevice() {
  if (registered || WiFi.status() != WL_CONNECTED || !validServerUrl(serverUrl)) return registered;
  JsonDocument doc;
  doc["uuid"] = deviceUuid;
  doc["secret"] = deviceSecret;
  doc["name"] = deviceName;
  String body;
  serializeJson(doc, body);
  WiFiClient transport;
  HTTPClient http;
  http.setTimeout(4000);
  if (!http.begin(transport, serverUrl + "/api/v1/devices/register")) return false;
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  http.end();
  if (code == 409) {
    authBlocked = true;
    showStatus("ID CONFLICT");
  }
  // Registration is unsigned. Only a subsequently signed /me reply is trusted.
  return code == 200;
}

bool pollDevice() {
  if (!settingsReady || !cryptoReady || WiFi.status() != WL_CONNECTED || !timeReady() ||
      !validServerUrl(serverUrl) || authBlocked) return false;
  if (!registered && !registerDevice()) return false;
  ApiReply reply = signedRequest("GET", "/api/v1/devices/me");
  if (!reply.verified) {
    if (reply.code > 0) showStatus("AUTH ERROR");
    return false;
  }
  if (reply.code == 401 || reply.code == 403) {
    authBlocked = true;
    approved = false;
    settings.putBool("approved", false);
    showStatus("DENIED");
    return false;
  }
  if (reply.code != 200) return false;
  JsonDocument doc;
  if (deserializeJson(doc, reply.body) || !doc["status"].is<const char *>() || !doc["paused"].is<bool>()) return false;
  String state = doc["status"].as<String>();
  approved = state == "approved";
  paused = doc["paused"].as<bool>();
  if (!approved || paused) enrollmentCredential = "";
  if (state == "revoked") authBlocked = true;
  registered = true;
  settings.putBool("registered", true);
  settings.putBool("approved", approved);
  settings.putBool("paused", paused);
  if (state == "pending") {
    if (statusText != "PENDING") showStatus("PENDING", currentClock());
  } else if (!approved || paused) {
    if (statusText != "DENIED" || statusDetail != state) showStatus("DENIED", state);
  } else if (enrollmentCredential.isEmpty()) {
    bool recentFeedback = (statusText == "OK" || statusText == "SAVED" || statusText == "OFFLINE SAVED" ||
                           statusText == "CARD ADDED" || statusText == "CARD EXISTS" ||
                           statusText == "ADD FAILED" || statusText == "ADD UNKNOWN" ||
                           statusText == "ADD TIMEOUT") &&
                          millis() - statusShownAt < 3000;
    if (statusText != "READY" && !recentFeedback) showStatus("READY", currentClock());
  }

  if (approved && doc["commands"].is<JsonArray>()) {
    for (JsonObject command : doc["commands"].as<JsonArray>()) {
      if (!command["id"].is<int>()) continue;
      int id = command["id"].as<int>();
      if (command["kind"] == "enroll_card") {
        String credential = command["credential"].as<String>();
        if (uidOrder == 0 || credential.length() != 64 || paused) continue;
        ApiReply ack = signedRequest("POST", "/api/v1/devices/me/commands/" + String(id) + "/ack");
        if (ack.verified && ack.code == 200) {
          enrollmentCredential = credential;
          enrollmentStarted = millis();
          showStatus("ADD CARD", "30 SEC");
        }
        continue;
      }
      if (command["kind"] != "restart") continue;
      ApiReply ack = signedRequest("POST", "/api/v1/devices/me/commands/" + String(id) + "/ack");
      if (ack.verified && ack.code == 200) {
        showStatus("RESTARTING");
        delay(300);
        ESP.restart();
      }
    }
  }
  return true;
}

String queuePath(uint32_t id, const char *extension) {
  char name[32];
  snprintf(name, sizeof(name), "/q/%010lu.%s", static_cast<unsigned long>(id), extension);
  return String(name);
}

size_t countQueue(bool includeBad = true) {
  if (!filesystemReady) return QUEUE_LIMIT;
  File dir = LittleFS.open("/q");
  if (!dir) return QUEUE_LIMIT;
  size_t count = 0;
  File file = dir.openNextFile();
  while (file) {
    String name = file.name();
    if (name.endsWith(".evt") || (includeBad && name.endsWith(".bad"))) ++count;
    file = dir.openNextFile();
  }
  return count;
}

void setupQueue() {
  filesystemReady = LittleFS.begin(false); // Never autoformat pending punches.
  if (!filesystemReady) { showStatus("STORAGE ERROR"); return; }
  if (!LittleFS.exists("/q") && !LittleFS.mkdir("/q")) {
    filesystemReady = false;
    showStatus("STORAGE ERROR");
    return;
  }
  File dir = LittleFS.open("/q");
  File file = dir.openNextFile();
  while (file) {
    String name = file.name();
    String base = name.substring(name.lastIndexOf('/') + 1);
    uint32_t id = strtoul(base.c_str(), nullptr, 10);
    if (id >= nextQueueId) nextQueueId = id + 1;
    if (name.endsWith(".tmp")) LittleFS.remove(name);
    file = dir.openNextFile();
  }
}

bool queuePunch(const String &uid, const String &timestamp) {
  if (!filesystemReady || countQueue() >= QUEUE_LIMIT || nextQueueId == 0) return false;
  uint32_t id = nextQueueId++;
  String temp = queuePath(id, "tmp"), event = queuePath(id, "evt");
  JsonDocument doc;
  doc["uid"] = uid;
  doc["timestamp"] = timestamp;
  doc["device_uuid"] = deviceUuid;
  File file = LittleFS.open(temp, FILE_WRITE);
  if (!file) return false;
  size_t written = serializeJson(doc, file);
  file.flush();
  size_t fileSize = file.size();
  file.close();
  if (written != measureJson(doc) || fileSize != written || !LittleFS.rename(temp, event)) {
    LittleFS.remove(temp);
    return false;
  }
  return true;
}

uint32_t oldestPending() {
  File dir = LittleFS.open("/q");
  if (!dir) return 0;
  uint32_t oldest = 0;
  File file = dir.openNextFile();
  while (file) {
    String name = file.name();
    if (name.endsWith(".evt")) {
      String base = name.substring(name.lastIndexOf('/') + 1);
      uint32_t id = strtoul(base.c_str(), nullptr, 10);
      if (id && (!oldest || id < oldest)) oldest = id;
    }
    file = dir.openNextFile();
  }
  return oldest;
}

void retryOne() {
  if (!filesystemReady || !approved || paused || authBlocked || !timeReady() || WiFi.status() != WL_CONNECTED) return;
  uint32_t id = oldestPending();
  if (!id) return;
  String path = queuePath(id, "evt");
  File file = LittleFS.open(path, FILE_READ);
  if (!file) { showStatus("STORAGE ERROR"); return; }
  JsonDocument stored;
  DeserializationError error = deserializeJson(stored, file);
  file.close();
  if (error || !stored["uid"].is<const char *>() || !stored["timestamp"].is<const char *>() ||
      stored["device_uuid"].as<String>() != deviceUuid) {
    LittleFS.rename(path, queuePath(id, "bad"));
    showStatus("QUEUE ERROR");
    return;
  }
  JsonDocument payload;
  payload["uid"] = stored["uid"].as<String>();
  payload["timestamp"] = stored["timestamp"].as<String>();
  String body;
  serializeJson(payload, body);
  ApiReply reply = signedRequest("POST", "/api/v1/punch", body);
  if (!reply.verified) {
    if (reply.code > 0) showStatus("AUTH ERROR");
    else showStatus("OFFLINE SAVED", currentClock());
    return;
  }
  if (reply.code == 200) {
    if (!LittleFS.remove(path)) showStatus("STORAGE ERROR");
    else showStatus("OK", currentClock());
  } else if (reply.code == 401 || reply.code == 403) {
    authBlocked = reply.code == 401;
    approved = false;
    settings.putBool("approved", false);
    showStatus("DENIED", "CHECK DEVICE");
    if (!authBlocked) lastPoll = millis() - pollInterval;
  } else if (reply.code == 400 || reply.code == 404) {
    if (!LittleFS.rename(path, queuePath(id, "bad"))) showStatus("STORAGE ERROR");
    else showStatus("PUNCH ERROR", String(reply.code));
  } else {
    showStatus("OFFLINE", currentClock());
  }
}

String uidHex(bool reversed) {
  uint8_t bytes[10];
  for (byte i = 0; i < rfid.uid.size; ++i) {
    bytes[i] = rfid.uid.uidByte[reversed ? rfid.uid.size - 1 - i : i];
  }
  return toHex(bytes, rfid.uid.size, true);
}

void scanCard() {
  if (calibrationPending && millis() - calibrationStarted > 60000) {
    calibrationPending = false;
    showStatus("CAL TIMEOUT");
  }
  if (cardLatched) {
    byte atqa[2], length = sizeof(atqa);
    MFRC522::StatusCode result = rfid.PICC_WakeupA(atqa, &length);
    if (result == MFRC522::STATUS_OK || result == MFRC522::STATUS_COLLISION) {
      // Return the present card to HALT so the next presence probe remains reliable.
      if (rfid.PICC_ReadCardSerial()) rfid.PICC_HaltA();
      cardAbsentSince = 0;
    } else if (!cardAbsentSince) {
      cardAbsentSince = millis();
    } else if (millis() - cardAbsentSince > 350) {
      cardLatched = false;
      cardAbsentSince = 0;
    }
    return;
  }
  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  String forward = uidHex(false), reverse = uidHex(true);
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  cardLatched = true;
  cardAbsentSince = 0;

  if (calibrationPending) {
    calibrationPending = false;
    Serial.print("RC522 UID: "); Serial.println(forward);
    Serial.print("Reversed:  "); Serial.println(reverse);
    bleNotifyLine(String("RC522 UID: ") + forward);
    bleNotifyLine(String("Reversed:  ") + reverse);
    if (expectedUid == forward) uidOrder = 1;
    else if (expectedUid == reverse) uidOrder = 2;
    else { uidOrder = 0; showStatus("UID MISMATCH"); return; }
    settings.putUChar("uid-order", uidOrder);
    showStatus("UID MATCH", uidOrder == 1 ? "NORMAL" : "REVERSED");
    return;
  }
  if (!enrollmentCredential.isEmpty()) {
    String credential = enrollmentCredential;
    enrollmentCredential = "";
    showStatus("READY", currentClock());
    JsonDocument payload;
    payload["uid"] = uidOrder == 1 ? forward : reverse;
    payload["credential"] = credential;
    String body;
    serializeJson(payload, body);
    ApiReply result = signedRequest("POST", "/api/v1/cards/empty", body);
    if (!result.verified) showStatus("ADD UNKNOWN", "CHECK ADMIN");
    else if (result.code == 200) showStatus("CARD ADDED", payload["uid"].as<String>());
    else if (result.code == 400) showStatus("CARD EXISTS", payload["uid"].as<String>());
    else showStatus("ADD FAILED", "HTTP " + String(result.code));
    return;
  }
  if (uidOrder == 0) { showStatus("SET UID ORDER"); return; }
  if (!settingsReady || !cryptoReady || !approved || paused || authBlocked) { showStatus("DENIED"); return; }
  if (!timeReady()) { showStatus("TIME UNSYNC"); return; }
  if (!filesystemReady) { showStatus("STORAGE ERROR"); return; }
  String timestamp = localTimestamp();
  if (timestamp.length() != 19 || !queuePunch(uidOrder == 1 ? forward : reverse, timestamp)) {
    showStatus("QUEUE FULL/ERR");
    return;
  }
  if (WiFi.status() != WL_CONNECTED) showStatus("OFFLINE SAVED", currentClock());
  else showStatus("SAVED", currentClock());
  lastRetry = millis() - RETRY_MS;
}

void printHelp(Print &out) {
  out.println("Commands: help | status | wifi <ssid> <password> | server <http://host:port> | name <text>");
  out.println("          calibrate <legacy UID> | init-storage NEW | queue | bad | discard-bad <id> | poll | selftest");
  out.println("Commands work over USB or paired BLE. Input is not masked by terminal apps.");
}

void listBad(Print &out) {
  if (!filesystemReady) return;
  File dir = LittleFS.open("/q");
  File file = dir.openNextFile();
  while (file) {
    String name = file.name();
    if (name.endsWith(".bad")) {
      JsonDocument doc;
      deserializeJson(doc, file);
      out.printf("%s UID=%s time=%s\n", name.c_str(),
                    doc["uid"].as<String>().c_str(), doc["timestamp"].as<String>().c_str());
    }
    file = dir.openNextFile();
  }
}

void processCommand(String line, Print &out) {
  line.trim();
  if (line == "help") printHelp(out);
  else if (line == "status") {
    out.printf("UUID=%s WiFi=%s server=%s approved=%d paused=%d uid-order=%u time=%d storage=%s queue=%u\n",
                  deviceUuid.c_str(), WiFi.status() == WL_CONNECTED ? "online" : "offline",
                  serverUrl.c_str(), approved, paused, uidOrder, timeReady(),
                  filesystemReady ? "ready" : "error", unsigned(countQueue()));
  } else if (line.startsWith("wifi ")) {
    String args = line.substring(5);
    int separator = args.indexOf(' ');
    if (separator <= 0) { out.println("Use: wifi <ssid> <password>"); return; }
    wifiSsid = args.substring(0, separator);
    wifiPassword = args.substring(separator + 1);
    settings.putString("ssid", wifiSsid);
    settings.putString("pass", wifiPassword);
    WiFi.disconnect();
    connectWifi();
    out.println("Wi-Fi saved; password is not printed.");
  } else if (line.startsWith("server ")) {
    String candidate = line.substring(7);
    candidate.trim();
    if (candidate.endsWith("/")) candidate.remove(candidate.length() - 1);
    if (!validServerUrl(candidate)) { out.println("Use an http://host:port URL without a path."); return; }
    serverUrl = candidate;
    settings.putString("server", serverUrl);
    registered = false;
    approved = false;
    authBlocked = false;
    settings.putBool("registered", false);
    settings.putBool("approved", false);
    out.println("Server saved; registration will be checked again.");
  } else if (line.startsWith("name ")) {
    String candidate = line.substring(5);
    candidate.trim();
    if (candidate.isEmpty() || candidate.length() > 100) { out.println("Name must be 1..100 characters."); return; }
    deviceName = candidate;
    settings.putString("name", deviceName);
    out.println("Name saved. Rename an already registered device in the admin UI.");
  } else if (line.startsWith("calibrate ")) {
    enrollmentCredential = "";
    expectedUid = line.substring(10);
    expectedUid.trim(); expectedUid.toUpperCase();
    uint8_t bytes[10];
    if ((expectedUid.length() != 8 && expectedUid.length() != 14 && expectedUid.length() != 20) ||
        !decodeHex(expectedUid, bytes, expectedUid.length() / 2)) {
      out.println("UID must be 8, 14, or 20 hexadecimal characters.");
      return;
    }
    uidOrder = 0;
    settings.putUChar("uid-order", 0);
    calibrationPending = true;
    calibrationStarted = millis();
    showStatus("TAP KNOWN CARD");
  } else if (line == "init-storage NEW") {
    if (filesystemReady) out.println("Storage already mounted; no formatting performed.");
    else {
      // Explicit first-install action. Never format automatically on a failed mount.
      LittleFS.end();
      filesystemReady = LittleFS.begin(true);
      if (filesystemReady) {
        if (!LittleFS.exists("/q")) filesystemReady = LittleFS.mkdir("/q");
        out.println(filesystemReady ? "Storage initialized." : "Storage initialization failed.");
      } else out.println("Storage initialization failed.");
    }
  } else if (line == "queue") {
    out.printf("Stored events: %u / %u; oldest pending ID: %lu\n", unsigned(countQueue()),
                  unsigned(QUEUE_LIMIT), static_cast<unsigned long>(filesystemReady ? oldestPending() : 0));
  } else if (line == "bad") listBad(out);
  else if (line == "selftest") out.println(protocolSelfTest() ? "Protocol self-test PASS" : "Protocol self-test FAIL");
  else if (line.startsWith("discard-bad ")) {
    uint32_t id = strtoul(line.substring(12).c_str(), nullptr, 10);
    if (!id || !LittleFS.remove(queuePath(id, "bad"))) out.println("Bad event not found.");
    else out.println("Bad event discarded.");
  } else if (line == "poll") { lastPoll = millis() - pollInterval; }
  else if (line.length()) out.println("Unknown command. Type help.");
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      processCommand(serialLine, Serial);
      serialLine = "";
    } else if (serialLine.length() < 220) serialLine += c;
    else serialLine = "";
  }
}

void readBle() {
  if (blePairingPin && bleConnected && !blePairingFinished && !blePinOnScreen) {
    char code[7];
    snprintf(code, sizeof(code), "%06lu", static_cast<unsigned long>(blePairingPin));
    tftShow("BLE PAIR", code);
    blePinOnScreen = true;
  }
  if (blePairingFinished) {
    blePairingFinished = false;
    blePairingPin = 0;
    if (blePinOnScreen) tftShow(statusText, statusDetail);
    blePinOnScreen = false;
  }
  if (!bleCommands) return;
  if (!bleConnected) { xQueueReset(bleCommands); return; }
  if (bleInputError) {
    bleInputError = false;
    bleNotifyLine("BLE command too long or busy; send it again.");
  }
  BleCommandLine line;
  if (xQueueReceive(bleCommands, &line, 0) == pdTRUE) {
    if (line.session != bleSession) return;
    ReaderBleReply reply;
    processCommand(String(line.text), reply);
    reply.flush();
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
  setupTft();
  showStatus("CVTA READER", "STARTING");
  loadSettings();
  setupBle();
  setupQueue();
  rfid.PCD_Init();
  WiFi.mode(WIFI_STA);
  sntp_set_time_sync_notification_cb(onNtpSync);
  connectWifi();
  printHelp(Serial);
  cryptoReady = protocolSelfTest();
  if (!cryptoReady) showStatus("CRYPTO ERROR");
  Serial.print("Device UUID: "); Serial.println(deviceUuid);
  if (!settingsReady) showStatus("CONFIG ERROR");
  else if (!cryptoReady) showStatus("CRYPTO ERROR");
  else if (!filesystemReady) showStatus("STORAGE ERROR");
  else if (uidOrder == 0) showStatus("SET UID ORDER");
  else if (wifiSsid.isEmpty() || serverUrl.isEmpty()) showStatus("SET NETWORK");
  else showStatus("TIME UNSYNC");
  lastPoll = millis() - pollInterval;
}

void loop() {
  readSerial();
  readBle();
  maintainWifi();
  bool wifiConnected = WiFi.status() == WL_CONNECTED;
  bool clockReady = timeReady();
  if (wifiConnected && !previousWifiConnected) lastPoll = millis() - pollInterval;
  if (clockReady && !previousTimeReady) {
    lastPoll = millis() - pollInterval;
    if (statusText == "TIME UNSYNC") {
      showStatus(approved && !paused ? "READY" : "PENDING", currentClock());
    }
  }
  if (!wifiConnected && previousWifiConnected && statusText == "READY") {
    showStatus("OFFLINE", currentClock());
  }
  previousWifiConnected = wifiConnected;
  previousTimeReady = clockReady;
  if (!enrollmentCredential.isEmpty() &&
      (!wifiConnected || !clockReady || millis() - enrollmentStarted >= 30000)) {
    bool timedOut = wifiConnected && clockReady && millis() - enrollmentStarted >= 30000;
    enrollmentCredential = "";
    showStatus(timedOut ? "ADD TIMEOUT" : "READY", currentClock());
  }
  if (wifiConnected && clockReady && settingsReady && cryptoReady && !authBlocked &&
      validServerUrl(serverUrl) && millis() - lastPoll >= pollInterval) {
    lastPoll = millis();
    pollInterval = pollDevice() ? STATE_POLL_MS : STATE_RETRY_MS;
  }
  scanCard();
  if (enrollmentCredential.isEmpty() && millis() - lastRetry >= RETRY_MS) {
    lastRetry = millis();
    retryOne();
  }
  if (!timeReady() && statusText != "TIME UNSYNC" && uidOrder && approved && !paused) {
    showStatus("TIME UNSYNC");
  }
  if ((statusText == "OK" || statusText == "SAVED" || statusText == "OFFLINE SAVED" ||
       statusText == "CARD ADDED" || statusText == "CARD EXISTS" ||
       statusText == "ADD FAILED" || statusText == "ADD UNKNOWN" ||
       statusText == "ADD TIMEOUT") &&
      millis() - statusShownAt >= 3000 && approved && !paused && !authBlocked &&
      uidOrder && timeReady()) {
    showStatus("READY", currentClock());
  }
  if ((statusText == "READY" || statusText == "PENDING") && millis() - lastClockRefresh >= 1000) {
    lastClockRefresh = millis();
    tftShow(statusText, currentClock());
  }
  delay(20);
}
