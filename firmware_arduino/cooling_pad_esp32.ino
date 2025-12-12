#include <DHT.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <math.h>
#include <WiFi.h>
#include <WebServer.h>

// ================= WIFI CONFIG =================
const char* WIFI_SSID = "Students";      // <-- change this
const char* WIFI_PASS = "Students";      // <-- change this

WebServer server(80);

// ================= OLED CONFIG (SH1106 1.3", I2C) =================
// Use HARDWARE I2C so it shares the bus with BH1750 on SDA=21, SCL=22
U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(
  U8G2_R0,
  U8X8_PIN_NONE  // reset pin not used
);

// ================= PIN CONFIG FOR NODEMCU ESP32 MD0245 =================

// Analog Inputs
const int PIN_LM35      = 33;   // LM35 temperature sensor
const int PIN_SHARP_IR  = 35;   // Sharp IR distance sensor
const int PIN_POT_FAN   = 34;   // Potentiometer for manual fan speed

// DHT22
const int PIN_DHT       = 16;   // DHT22 data pin
#define DHTTYPE DHT22
DHT dht(PIN_DHT, DHTTYPE);

// Mode Button (AUTO / MANUAL)
const int PIN_BUTTON    = 23;   // push button to GND, use INPUT_PULLUP

// Mode Indicator LEDs
const int PIN_LED_AUTO  = 2;    // AUTO mode LED
const int PIN_LED_MAN   = 4;    // MANUAL mode LED

// Actuators
const int PIN_FAN       = 25;   // Fan MOSFET gate (PWM)
const int PIN_BUZZER    = 27;   // Buzzer

// ================= RGB / DECORATIVE LED PINS =================
// LEDs for chasing pattern
const int RGB_PINS[] = {17, 5, 18, 19, 26};
const int NUM_RGB = sizeof(RGB_PINS) / sizeof(RGB_PINS[0]);

// ================= BH1750 (GY-30) LIGHT SENSOR =================
// Use 0x23 if ADD/AD0 is LOW or floating, 0x5C if tied to VCC
#define BH1750_ADDR 0x23
const float LUX_THRESHOLD = 99.0;  // below this = dark -> RGB ON

// ================= MODE & BUTTON STATE =================
bool autoMode = true;               // true = AUTO, false = MANUAL

int buttonState      = HIGH;        // debounced button state
int lastButtonRead   = HIGH;        // last raw read
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 50; // ms for debouncing

// ================= THRESHOLDS =================
// Temperature thresholds (tune as needed)
float TEMP_LOW  = 30.0;  // below this → fan off/low
float TEMP_MED  = 40.0;  // medium speed
float TEMP_MAX  = 50.0;  // above this → continuous alarm

// IR raw thresholds for mapping to distance (tune by calibration)
const int IR_RAW_NEAR = 2500;  // raw when object very close (~10cm)
const int IR_RAW_FAR  = 500;   // raw when object far (~80cm)

// State for "<10cm" detection (for 2-beep)
bool lastVeryNear = false;

// Track current fan duty for display
uint8_t currentFanDuty = 0;

// For small display animation (manual bar marker)
bool animState = false;

// Remember last pot value (for display)
int lastPotRaw = 0;

// ================= NON-BLOCKING BUZZER STATE =================
enum BuzzerState { BUZZER_IDLE, BUZZER_ON, BUZZER_OFF_GAP };
BuzzerState buzzerState = BUZZER_IDLE;
int buzzerBeepRemaining = 0;
unsigned long buzzerLastChange = 0;
uint16_t buzzerOnMs = 80;
uint16_t buzzerOffMs = 80;

// ================= NON-BLOCKING MODE OVERLAY =================
bool showModeOverlay = false;
unsigned long modeOverlayUntil = 0;
const unsigned long MODE_OVERLAY_DURATION = 700; // ms

// ================= NON-BLOCKING SENSOR TIMING =================
float dhtTempCached = NAN;
float dhtHumCached  = NAN;
unsigned long lastDhtMillis = 0;
const uint32_t DHT_INTERVAL = 2000; // ms

float luxCached = -1.0;
unsigned long lastLuxMillis = 0;
const uint32_t LUX_INTERVAL = 500; // ms

// ================= RGB CHASING PATTERN STATE =================
int rgbIndex = 0;
unsigned long lastRgbStep = 0;
const uint32_t RGB_INTERVAL = 150; // ms between steps (adjust speed)

// ================= GLOBALS FOR WEB STATUS =================
float g_lm35TempC = 0;
float g_dhtTemp   = 0;
float g_dhtHum    = 0;
float g_distCm    = 0;
float g_lux       = 0;
int   g_potRaw    = 0;
bool  g_connected = false;

// ========== NEW: REMOTE CONTROL FLAGS (from Python GUI) ==========
bool   remoteFanOverride     = false;   // if true, use remoteFanDutyCmd in MANUAL mode
uint8_t remoteFanDutyCmd     = 0;       // 0–255

bool   remoteRgbOverride     = false;   // if true, ignore AUTO/MANUAL RGB logic
bool   remoteRgbEnableCmd    = false;   // true = chase ON, false = OFF

bool   remoteBuzzerContinuous = false;  // true = keep buzzer ON (unless overtemp alarm)

// ================= SIMPLE WEB PAGE (HTML) =================
const char MAIN_page[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>ESP32 Cooling Pad</title>
  <style>
    body { font-family: Arial, sans-serif; background: #0f172a; color: #e5e7eb; margin: 0; padding: 16px; }
    .card { background:#111827; border-radius:12px; padding:16px 20px; max-width:500px; margin:auto; box-shadow:0 10px 25px rgba(0,0,0,0.4);}
    h2 { margin-top:0; }
    .row { display:flex; justify-content:space-between; margin:6px 0; }
    .label { color:#9ca3af; }
    .value { font-weight:bold; }
    button { padding:8px 16px; border:none; border-radius:999px; margin-right:8px; cursor:pointer; font-weight:600; }
    .auto { background:#22c55e; color:#022c22; }
    .manual { background:#3b82f6; color:#e0f2fe; }
    .active { box-shadow:0 0 0 2px #fbbf24; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Smart Gaming Laptop Cooling Pad</h2>
    <div class="row"><span class="label">Mode</span><span class="value" id="mode">-</span></div>
    <div class="row"><span class="label">LM35 Temp</span><span class="value" id="lm35">-</span></div>
    <div class="row"><span class="label">DHT Temp</span><span class="value" id="dhtt">-</span></div>
    <div class="row"><span class="label">Humidity</span><span class="value" id="dhth">-</span></div>
    <div class="row"><span class="label">Distance</span><span class="value" id="dist">-</span></div>
    <div class="row"><span class="label">Lux</span><span class="value" id="lux">-</span></div>
    <div class="row"><span class="label">Fan Duty</span><span class="value" id="fan">-</span></div>
    <div class="row"><span class="label">Connected</span><span class="value" id="conn">-</span></div>
    <hr>
    <div>
      <button id="btnAuto"   class="auto"   onclick="setMode('AUTO')">AUTO MODE</button>
      <button id="btnManual" class="manual" onclick="setMode('MANUAL')">MANUAL MODE</button>
    </div>
  </div>

<script>
function refreshStatus(){
  fetch('/status')
    .then(r => r.json())
    .then(d => {
      document.getElementById('mode').textContent = d.mode;
      document.getElementById('lm35').textContent = d.lm35.toFixed(1) + " °C";
      document.getElementById('dhtt').textContent = d.dhtTemp.toFixed(1) + " °C";
      document.getElementById('dhth').textContent = d.dhtHum.toFixed(0) + " %";
      document.getElementById('dist').textContent = d.dist.toFixed(0) + " cm";
      document.getElementById('lux').textContent  = d.lux.toFixed(0) + " lx";
      document.getElementById('fan').textContent  = d.fanDuty;
      document.getElementById('conn').textContent = d.connected ? "YES" : "NO";

      document.getElementById('btnAuto').classList.remove('active');
      document.getElementById('btnManual').classList.remove('active');
      if (d.mode === "AUTO") document.getElementById('btnAuto').classList.add('active');
      else document.getElementById('btnManual').classList.add('active');
    })
    .catch(e => console.log(e));
}

function setMode(m){
  fetch('/setMode?mode=' + m)
    .then(r => r.text())
    .then(t => console.log(t))
    .catch(e => console.log(e));
}

setInterval(refreshStatus, 1000);
refreshStatus();
</script>
</body>
</html>
)rawliteral";

// ================= IR DISTANCE HELPER =================
// Approximate distance in cm from Sharp IR raw value.
float estimateDistanceCm(int irRaw) {
  int clamped = constrain(irRaw, IR_RAW_FAR, IR_RAW_NEAR);
  long distLong = map(clamped, IR_RAW_NEAR, IR_RAW_FAR, 10, 80); // 10cm close, 80cm far
  return (float)distLong;
}

// ================= ADC READ HELPER =================
// Read ADC twice to reduce channel switching noise / interference.
int readAdcSmooth(int pin) {
  analogRead(pin);             // throw away first sample
  delayMicroseconds(50);       // small settle time
  int val = analogRead(pin);   // use second sample
  return val;
}

// ================= LM35 READ HELPER =================
float readLM35TempC() {
  int raw = readAdcSmooth(PIN_LM35);
  // ESP32: ADC 0–4095 at 0–3.3V
  float voltage = (raw * 3.3f) / 4095.0f;
  float tempC   = voltage * 100.0f;  // LM35: 10mV/°C
  return tempC;
}

// ================= BH1750 HELPERS =================
// Initialize BH1750 sensor in continuous high-res mode
void bh1750Begin() {
  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(0x01);  // Power ON
  Wire.endTransmission();
  delay(10);
  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(0x10);  // Continuous high resolution mode (1 lx resolution)
  Wire.endTransmission();
}

// Non-blocking lux update (called often, updates every LUX_INTERVAL ms)
void updateLux() {
  unsigned long now = millis();
  if (now - lastLuxMillis >= LUX_INTERVAL) {
    lastLuxMillis = now;

    Wire.requestFrom(BH1750_ADDR, 2);
    if (Wire.available() == 2) {
      uint16_t level = (Wire.read() << 8) | Wire.read();
      luxCached = level / 1.2f;
    }
  }
}

// ================= DHT NON-BLOCKING UPDATE =================
void updateDht() {
  unsigned long now = millis();
  if (now - lastDhtMillis >= DHT_INTERVAL) {
    lastDhtMillis = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (!isnan(t)) dhtTempCached = t;
    if (!isnan(h)) dhtHumCached  = h;
  }
}

// ================= BUZZER HELPERS (NON-BLOCKING PATTERN) =================
void startBeepPattern(int count, int onMs = 80, int offMs = 80) {
  if (count <= 0) {
    buzzerState = BUZZER_IDLE;
    digitalWrite(PIN_BUZZER, LOW);
    return;
  }
  buzzerBeepRemaining = count;
  buzzerOnMs  = onMs;
  buzzerOffMs = offMs;
  buzzerState = BUZZER_ON;
  buzzerLastChange = millis();
  digitalWrite(PIN_BUZZER, HIGH);
}

void updateBuzzer() {
  if (buzzerState == BUZZER_IDLE) {
    digitalWrite(PIN_BUZZER, LOW);
    return;
  }

  unsigned long now = millis();

  if (buzzerState == BUZZER_ON) {
    if (now - buzzerLastChange >= buzzerOnMs) {
      digitalWrite(PIN_BUZZER, LOW);
      buzzerLastChange = now;
      buzzerState = BUZZER_OFF_GAP;
      buzzerBeepRemaining--;
    }
  } else if (buzzerState == BUZZER_OFF_GAP) {
    if (now - buzzerLastChange >= buzzerOffMs) {
      if (buzzerBeepRemaining > 0) {
        digitalWrite(PIN_BUZZER, HIGH);
        buzzerLastChange = now;
        buzzerState = BUZZER_ON;
      } else {
        buzzerState = BUZZER_IDLE;
        digitalWrite(PIN_BUZZER, LOW);
      }
    }
  }
}

// ================= MODE LED UPDATE =================
void updateModeIndicators() {
  if (autoMode) {
    digitalWrite(PIN_LED_AUTO, HIGH);
    digitalWrite(PIN_LED_MAN, LOW);
  } else {
    digitalWrite(PIN_LED_AUTO, LOW);
    digitalWrite(PIN_LED_MAN, HIGH);
  }
}

// Helper to set mode from button OR web
void setMode(bool newAuto) {
  if (autoMode == newAuto) return;
  autoMode = newAuto;
  updateModeIndicators();

  // When switching mode, it's safe to drop remote overrides (optional)
  if (autoMode) {
    remoteFanOverride      = false;
    remoteRgbOverride      = false;
    remoteBuzzerContinuous = false;
  }

  // Beep feedback: 1 beep for AUTO, 2 beeps for MANUAL (non-blocking)
  if (autoMode) {
    startBeepPattern(1);
  } else {
    startBeepPattern(2);
  }

  // Show mode overlay on OLED (non-blocking)
  showModeOverlay = true;
  modeOverlayUntil = millis() + MODE_OVERLAY_DURATION;
}

// ================= RGB HELPERS =================
void setAllRgb(bool on) {
  for (int i = 0; i < NUM_RGB; i++) {
    digitalWrite(RGB_PINS[i], on ? HIGH : LOW);
  }
}

// Non-blocking chasing pattern: one LED ON at a time, others OFF
void updateRgbChase(bool enabled) {
  if (!enabled) {
    setAllRgb(false);
    return;
  }

  unsigned long now = millis();
  if (now - lastRgbStep >= RGB_INTERVAL) {
    lastRgbStep = now;

    // Move to next LED
    rgbIndex++;
    if (rgbIndex >= NUM_RGB) rgbIndex = 0;

    // Light only the current LED
    for (int i = 0; i < NUM_RGB; i++) {
      digitalWrite(RGB_PINS[i], (i == rgbIndex) ? HIGH : LOW);
    }
  }
}

// ================= OLED (U8g2) HELPERS =================

// Startup animated title (Smart Gaming Laptop Cooling Pad)
void showStartupAnimation() {
  u8g2.clearBuffer();

  // Step 0: Starting Text
  u8g2.setFont(u8g2_font_t0_12_tr); // clean, narrow font
  u8g2.drawStr(15, 32, "Starting System...");
  u8g2.sendBuffer();
  delay(1200);
  u8g2.clearBuffer();

  // Step 1: "ESP32-Based" Slide-In (Left)
  u8g2.setFont(u8g2_font_t0_12_tr); // compact, tight spacing
  for (int x = -128; x <= 10; x += 6) {
    u8g2.clearBuffer();
    u8g2.drawStr(x, 22, "ESP32-Based");
    u8g2.sendBuffer();
    delay(60);
  }
  delay(400);

  // Step 2: "Smart Gaming" Slide-In (Right)
  for (int x = 128; x >= 10; x -= 6) {
    u8g2.clearBuffer();
    u8g2.drawStr(10, 22, "ESP32-Based");
    u8g2.drawStr(x, 38, "Smart Gaming");
    u8g2.sendBuffer();
    delay(60);
  }
  delay(500);

  // Step 3: Fade-in "Laptop Cooling Pad"
  for (int i = 0; i < 3; i++) {
    u8g2.clearBuffer();
    u8g2.drawStr(10, 22, "ESP32-Based");
    u8g2.drawStr(10, 38, "Smart Gaming");
    u8g2.drawStr(10, 54, "Laptop Cooling Pad");
    u8g2.sendBuffer();
    delay(300);
  }
  delay(600);

  // Loading Bar
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_t0_12_tr);
  u8g2.drawStr(30, 32, "Loading...");
  u8g2.drawFrame(10, 40, 108, 10); // outer box

  for (int i = 0; i <= 104; i += 4) {
    u8g2.drawBox(12, 42, i, 6);  // fill the loading bar
    u8g2.sendBuffer();
    delay(120);
  }

  delay(800);
  u8g2.clearBuffer();
}

// Draw mode overlay (AUTO / MANUAL)
void drawModeOverlay() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_logisoso22_tf);
  const char* text = autoMode ? "AUTO" : "MANUAL";
  u8g2.drawStr(10, 40, text);
  u8g2.sendBuffer();
}

// ================= AUTO MODE SCREEN =================
void drawAutoModeScreen(float lm35TempC, float dhtTemp, float dhtHum,
                        float distCm, float lux, uint8_t fanDuty) {

  u8g2.clearBuffer();

  // Top line: mode + fan duty
  u8g2.setFont(u8g2_font_5x7_tr);
  u8g2.drawStr(0, 8, "AUTO MODE");
  u8g2.setCursor(80, 8);
  u8g2.print("F:");
  u8g2.print(fanDuty);

  // Line 2: LM35
  u8g2.setCursor(0, 20);
  u8g2.print("LM35: ");
  u8g2.print(lm35TempC, 1);
  u8g2.print(" C");

  // Line 3: DHT
  u8g2.setCursor(0, 30);
  u8g2.print("DHT: ");
  if (isnan(dhtTemp) || isnan(dhtHum)) {
    u8g2.print("-- C -- %");
  } else {
    u8g2.print(dhtTemp, 1);
    u8g2.print(" C ");
    u8g2.print(dhtHum, 0);
    u8g2.print(" %");
  }

  // Line 4: Distance + Lux
  u8g2.setCursor(0, 40);
  u8g2.print("D:");
  u8g2.print(distCm, 0);
  u8g2.print("cm Lx:");
  u8g2.print(lux, 0);

  // Line 5: Status
  u8g2.setCursor(0, 52);
  u8g2.print("Status: ");
  if (distCm > 0 && distCm <= 10.0) {
    u8g2.print("CONNECTED");
  } else {
    u8g2.print("NOT CONNECTED");
  }

  u8g2.sendBuffer();
}

// ================= MANUAL MODE SCREEN =================
void drawManualModeScreen(float lm35TempC, float dhtTemp, float dhtHum,
                          int potRaw, float lux, uint8_t fanDuty) {

  int fanPercent = map(fanDuty, 0, 255, 0, 100);
  fanPercent = constrain(fanPercent, 0, 100);

  u8g2.clearBuffer();

  // Top line: mode + fan duty
  u8g2.setFont(u8g2_font_5x7_tr);
  u8g2.drawStr(0, 8, "MANUAL MODE");
  u8g2.setCursor(80, 8);
  u8g2.print("F:");
  u8g2.print(fanDuty);

  // Line 2: LM35
  u8g2.setCursor(0, 20);
  u8g2.print("LM35: ");
  u8g2.print(lm35TempC, 1);
  u8g2.print(" C");

  // Line 3: DHT
  u8g2.setCursor(0, 30);
  u8g2.print("DHT: ");
  if (isnan(dhtTemp) || isnan(dhtHum)) {
    u8g2.print("-- C -- %");
  } else {
    u8g2.print(dhtTemp, 1);
    u8g2.print(" C ");
    u8g2.print(dhtHum, 0);
    u8g2.print(" %");
  }

  // Line 4: Fan percentage
  u8g2.setCursor(0, 40);
  u8g2.print("Fan: ");
  u8g2.print(fanPercent);
  u8g2.print(" %");

  // Line 5: Pot + Lux
  u8g2.setCursor(0, 52);
  u8g2.print("Pot:");
  u8g2.print(potRaw);
  u8g2.print(" Lx:");
  u8g2.print(lux, 0);

  // Bottom bar graph
  int barX = 0;
  int barY = 58;
  int barWidth = 120;
  int barHeight = 6;

  u8g2.drawFrame(barX, barY, barWidth, barHeight);

  int fillWidth = map(fanPercent, 0, 100, 0, barWidth - 2);
  fillWidth = constrain(fillWidth, 0, barWidth - 2);

  u8g2.drawBox(barX + 1, barY + 1, fillWidth, barHeight - 2);

  // Small animated marker at the end of bar
  int markerX = barX + 1 + fillWidth;
  if (markerX > barX + barWidth - 2) markerX = barX + barWidth - 2;
  if (animState) {
    u8g2.drawLine(markerX, barY + 1, markerX, barY + barHeight - 2);
  }

  u8g2.sendBuffer();

  // Toggle animation state
  animState = !animState;
}

// ================= BUTTON HANDLING (AUTO/MANUAL TOGGLE) =================
void handleModeButton() {
  int reading = digitalRead(PIN_BUTTON);

  // Debounce
  if (reading != lastButtonRead) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != buttonState) {
      buttonState = reading;

      // Button is active LOW (INPUT_PULLUP)
      if (buttonState == LOW) {
        // Toggle mode using common helper
        setMode(!autoMode);
      }
    }
  }

  lastButtonRead = reading;
}

// ================= HTTP HANDLERS =================
void handleRoot() {
  server.send(200, "text/html", MAIN_page);
}

void handleStatus() {
  // Avoid NaN in JSON (replace with 0 if needed)
  float dhtT = isnan(g_dhtTemp) ? 0.0 : g_dhtTemp;
  float dhtH = isnan(g_dhtHum) ? 0.0 : g_dhtHum;
  float lux  = (g_lux < 0) ? 0.0 : g_lux;

  String json = "{";
  json += "\"mode\":\"";
  json += (autoMode ? "AUTO" : "MANUAL");
  json += "\",";
  json += "\"lm35\":"     + String(g_lm35TempC, 1) + ",";
  json += "\"dhtTemp\":"  + String(dhtT, 1)        + ",";
  json += "\"dhtHum\":"   + String(dhtH, 1)        + ",";
  json += "\"dist\":"     + String(g_distCm, 1)    + ",";
  json += "\"lux\":"      + String(lux, 1)         + ",";
  json += "\"fanDuty\":"  + String(currentFanDuty) + ",";
  json += "\"connected\":"+ String(g_connected ? "true" : "false");
  json += "}";
  server.send(200, "application/json", json);
}

void handleSetMode() {
  if (!server.hasArg("mode")) {
    server.send(400, "text/plain", "Missing mode param");
    return;
  }
  String m = server.arg("mode");
  m.toUpperCase();
  if (m == "AUTO") {
    setMode(true);
    server.send(200, "text/plain", "OK AUTO");
  } else if (m == "MANUAL") {
    setMode(false);
    server.send(200, "text/plain", "OK MANUAL");
  } else {
    server.send(400, "text/plain", "Unknown mode");
  }
}

// ===== NEW: /fan HTTP handler (remote fan duty) =====
//  - /fan?duty=0..255  -> sets fan speed and enables override (MANUAL mode)
//  - /fan?release=1    -> disable override, back to POT
void handleFan() {
  if (server.hasArg("release")) {
    remoteFanOverride = false;
    server.send(200, "text/plain", "Fan override released");
    return;
  }
  if (!server.hasArg("duty")) {
    server.send(400, "text/plain", "Missing duty param (0-255)");
    return;
  }
  int duty = server.arg("duty").toInt();
  duty = constrain(duty, 0, 255);
  remoteFanDutyCmd = (uint8_t)duty;
  remoteFanOverride = true;
  server.send(200, "text/plain", "Fan duty set");
}

// ===== NEW: /rgb HTTP handler (remote RGB ON/OFF) =====
//  - /rgb?state=ON     -> chase pattern ON (override)
//  - /rgb?state=OFF    -> all OFF (override)
//  - /rgb?release=1    -> release override, revert to normal logic
void handleRgb() {
  if (server.hasArg("release")) {
    remoteRgbOverride = false;
    server.send(200, "text/plain", "RGB override released");
    return;
  }
  if (!server.hasArg("state")) {
    server.send(400, "text/plain", "Missing state param (ON/OFF)");
    return;
  }
  String st = server.arg("state");
  st.toUpperCase();
  if (st == "ON") {
    remoteRgbOverride  = true;
    remoteRgbEnableCmd = true;
    server.send(200, "text/plain", "RGB ON");
  } else if (st == "OFF") {
    remoteRgbOverride  = true;
    remoteRgbEnableCmd = false;
    server.send(200, "text/plain", "RGB OFF");
  } else {
    server.send(400, "text/plain", "Unknown state (use ON/OFF)");
  }
}

// ===== NEW: /buzzer HTTP handler =====
//  - /buzzer?pattern=N -> N beeps using existing pattern (non-blocking)
//  - /buzzer?state=ON  -> continuous ON (until state=OFF)
//  - /buzzer?state=OFF -> stop continuous and patterns
void handleBuzzerHttp() {
  if (server.hasArg("pattern")) {
    int count = server.arg("pattern").toInt();
    if (count < 1) count = 1;
    remoteBuzzerContinuous = false;   // pattern mode, not continuous
    startBeepPattern(count);
    server.send(200, "text/plain", "Beep pattern started");
    return;
  }

  if (server.hasArg("state")) {
    String st = server.arg("state");
    st.toUpperCase();
    if (st == "ON") {
      remoteBuzzerContinuous = true;
      buzzerState = BUZZER_IDLE;    // stop pattern, use continuous
      digitalWrite(PIN_BUZZER, HIGH);
      server.send(200, "text/plain", "Buzzer continuous ON");
    } else if (st == "OFF") {
      remoteBuzzerContinuous = false;
      buzzerState = BUZZER_IDLE;
      digitalWrite(PIN_BUZZER, LOW);
      server.send(200, "text/plain", "Buzzer OFF");
    } else {
      server.send(400, "text/plain", "Unknown state (use ON/OFF)");
    }
    return;
  }

  server.send(400, "text/plain", "Provide pattern or state param");
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);

  // ESP32 HARDWARE I2C pins for OLED + BH1750
  Wire.begin(21, 22); // SDA=21, SCL=22

  // OLED init (U8g2 on hardware I2C)
  u8g2.begin();
  showStartupAnimation();

  dht.begin();
  bh1750Begin();   // init light sensor

  // Inputs
  pinMode(PIN_BUTTON, INPUT_PULLUP);   // button → GND

  // Outputs
  pinMode(PIN_LED_AUTO, OUTPUT);
  pinMode(PIN_LED_MAN, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);

  // RGB pins
  for (int i = 0; i < NUM_RGB; i++) {
    pinMode(RGB_PINS[i], OUTPUT);
    digitalWrite(RGB_PINS[i], LOW);
  }

  digitalWrite(PIN_BUZZER, LOW);
  analogWrite(PIN_FAN, 0);
  setAllRgb(false);

  autoMode = true;
  updateModeIndicators();

  // -------- WIFI CONNECT ---------
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected!");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  // HTTP routes
  server.on("/",        handleRoot);
  server.on("/status",  handleStatus);
  server.on("/setMode", handleSetMode);

  // NEW routes for Python GUI
  server.on("/fan",     handleFan);
  server.on("/rgb",     handleRgb);
  server.on("/buzzer",  handleBuzzerHttp);

  server.begin();
  Serial.println("HTTP server started");
}

// ================= MAIN LOOP =================
void loop() {
  // 1) Handle HTTP clients
  server.handleClient();

  // 2) Handle button (mode switch)
  handleModeButton();

  // 3) Update sensors on their own schedules
  updateDht();
  updateLux();

  // 4) Read fast sensors (every loop)
  float lm35TempC = readLM35TempC();
  int   irRaw     = readAdcSmooth(PIN_SHARP_IR);

  // Pot will be read later only in MANUAL mode
  int potRaw = lastPotRaw;

  // 5) Use cached DHT & Lux values
  float dhtTemp = dhtTempCached;
  float dhtHum  = dhtHumCached;
  float lux     = luxCached;

  // 6) Estimate distance from IR
  float distCm = estimateDistanceCm(irRaw);

  // IR-based flags
  bool connected     = (distCm > 0 && distCm <= 10.0);   // for RGB enable
  bool laptopPresent = (distCm > 0 && distCm < 40.0);    // for fan control

  // Overtemp alarm flag
  bool overTempAlarm = false;

  // ------------ AUTO MODE ------------
  if (autoMode) {
    uint8_t fanDuty = 0;

    if (laptopPresent) {
      // LM35 controls fan speed
      if (lm35TempC < TEMP_LOW) {
        fanDuty = 0;         // fan OFF
      } else if (lm35TempC < TEMP_MED) {
        fanDuty = 140;       // medium speed
      } else {
        fanDuty = 255;       // full speed
      }

      if (lm35TempC > TEMP_MAX) {
        overTempAlarm = true;
      }
    } else {
      // No laptop detected → fan OFF
      fanDuty = 0;
    }

    currentFanDuty = fanDuty;
    analogWrite(PIN_FAN, currentFanDuty);

    // ---------- RGB: AUTO MODE ----------
    bool rgbEnable;
    if (remoteRgbOverride) {
      // If override from Python -> use command
      rgbEnable = remoteRgbEnableCmd;
    } else {
      // Normal auto logic
      rgbEnable = false;
      if (connected && lux >= 0) {
        if (lux < LUX_THRESHOLD) {
          rgbEnable = true;   // DARK → pattern ON
        } else {
          rgbEnable = false;  // BRIGHT → OFF
        }
      } else {
        rgbEnable = false;    // Not connected or lux error → OFF
      }
    }
    updateRgbChase(rgbEnable);

  // ------------ MANUAL MODE ------------
  } else {
    // Now read POT ONLY in manual mode, and read it last (to reduce cross-talk)
    potRaw = analogRead(PIN_POT_FAN);
    lastPotRaw = potRaw;

    // Fan in MANUAL:
    //  - If Python override active -> use remoteFanDutyCmd
    //  - Else -> use potentiometer
    uint8_t fanDuty;
    if (remoteFanOverride) {
      fanDuty = remoteFanDutyCmd;
    } else {
      fanDuty = map(potRaw, 0, 4095, 0, 255);
    }
    currentFanDuty = fanDuty;
    analogWrite(PIN_FAN, currentFanDuty);

    // RGB: MANUAL
    bool rgbEnable;
    if (remoteRgbOverride) {
      rgbEnable = remoteRgbEnableCmd;
    } else {
      // default MANUAL: pattern ON
      rgbEnable = true;
    }
    updateRgbChase(rgbEnable);

    // No automatic over-temp alarm in manual mode
    overTempAlarm = false;
  }

  // ------------ IR <10cm DETECTION BEEP (any mode, non-blocking) ------------
  bool veryNear = (distCm <= 10.0);  // "below or equal 10cm"
  if (veryNear && !lastVeryNear) {
    // Just entered <10cm zone → 2-beep pattern
    startBeepPattern(2);
  }
  lastVeryNear = veryNear;

  // ------------ BUZZER CONTROL (priority: overtemp > remote continuous > patterns) ------------
  if (overTempAlarm) {
    // Continuous alarm: override any pattern or remote continuous
    remoteBuzzerContinuous = false;
    buzzerState = BUZZER_IDLE;
    digitalWrite(PIN_BUZZER, HIGH);
  } else if (remoteBuzzerContinuous) {
    // Python wants buzzer ON
    buzzerState = BUZZER_IDLE;
    digitalWrite(PIN_BUZZER, HIGH);
  } else {
    updateBuzzer();  // handle any active beep pattern (or keep off)
  }

  // ------------ DEBUG SERIAL OUTPUT ------------
  Serial.print("MODE: ");
  Serial.print(autoMode ? "AUTO" : "MANUAL");
  Serial.print(" | LM35: ");
  Serial.print(lm35TempC);
  Serial.print(" C | IR Raw: ");
  Serial.print(irRaw);
  Serial.print(" | Dist: ");
  Serial.print(distCm);
  Serial.print(" cm | CONNECTED: ");
  Serial.print(connected ? "YES" : "NO");
  Serial.print(" | Lux: ");
  Serial.print(lux);
  Serial.print(" lx | Pot: ");
  Serial.print(potRaw);
  Serial.print(" | DHT T: ");
  Serial.print(dhtTemp);
  Serial.print(" C | H: ");
  Serial.print(dhtHum);
  Serial.print(" % | FanDuty: ");
  Serial.println(currentFanDuty);

  // Save to globals for /status
  g_lm35TempC = lm35TempC;
  g_dhtTemp   = dhtTemp;
  g_dhtHum    = dhtHum;
  g_distCm    = distCm;
  g_lux       = lux;
  g_potRaw    = potRaw;
  g_connected = connected;

  // ------------ OLED STATUS SCREEN (U8g2) ------------
  if (showModeOverlay && (millis() < modeOverlayUntil)) {
    drawModeOverlay();
  } else {
    showModeOverlay = false;
    if (autoMode) {
      drawAutoModeScreen(lm35TempC, dhtTemp, dhtHum, distCm, lux, currentFanDuty);
    } else {
      drawManualModeScreen(lm35TempC, dhtTemp, dhtHum, potRaw, lux, currentFanDuty);
    }
  }
}
