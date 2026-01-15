#include <DHT.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <math.h>
#include <WiFi.h>
#include <WebServer.h>

// ================= WIFI CONFIG =================
const char* WIFI_SSID = "ESP32TEST";           // <-- change this
const char* WIFI_PASS = "12345678";            // <-- change this

WebServer server(80);

// ================= OLED CONFIG (SH1106 1.3", I2C) =================
U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(
  U8G2_R0,
  U8X8_PIN_NONE
);

// ================= PIN CONFIG FOR NODEMCU ESP32 MD0245 =================

// Analog Inputs
const int PIN_LM35      = 33;
const int PIN_SHARP_IR  = 35;
const int PIN_POT_FAN   = 34;

// DHT22
const int PIN_DHT       = 16;
#define DHTTYPE DHT22
DHT dht(PIN_DHT, DHTTYPE);

// Mode Button (AUTO / MANUAL)
const int PIN_BUTTON    = 23;

// Mode Indicator LEDs
const int PIN_LED_AUTO  = 2;
const int PIN_LED_MAN   = 4;

// Actuators
const int PIN_FAN       = 25;   // Fan MOSFET gate (PWM)  -> analogWrite
const int PIN_BUZZER    = 27;

// ================= RGB / DECORATIVE LED PINS =================
const int RGB_PINS[] = {17, 5, 18, 19, 26};
const int NUM_RGB = sizeof(RGB_PINS) / sizeof(RGB_PINS[0]);

// ================= BH1750 (GY-30) LIGHT SENSOR =================
#define BH1750_ADDR 0x23
const float LUX_THRESHOLD = 99.0;

// ================= MODE & BUTTON STATE =================
bool autoMode = true;

int buttonState      = HIGH;
int lastButtonRead   = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 50;

// ================= THRESHOLDS =================
float TEMP_LOW  = 30.0;
float TEMP_MED  = 40.0;
float TEMP_MAX  = 50.0;

const int IR_RAW_NEAR = 2500;
const int IR_RAW_FAR  = 500;

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
const unsigned long MODE_OVERLAY_DURATION = 700;

// ================= NON-BLOCKING SENSOR TIMING =================
float dhtTempCached = NAN;
float dhtHumCached  = NAN;
unsigned long lastDhtMillis = 0;
const uint32_t DHT_INTERVAL = 2000;

float luxCached = -1.0;
unsigned long lastLuxMillis = 0;
const uint32_t LUX_INTERVAL = 500;

// ================= RGB CHASING PATTERN STATE =================
int rgbIndex = 0;
unsigned long lastRgbStep = 0;
const uint32_t RGB_INTERVAL = 150;

// ================= GLOBALS FOR WEB STATUS =================
float g_lm35TempC = 0;
float g_dhtTemp   = 0;
float g_dhtHum    = 0;
float g_distCm    = 0;
float g_lux       = 0;
int   g_potRaw    = 0;
bool  g_connected = false;

// ========== REMOTE CONTROL FLAGS (from Python GUI) ==========
bool   remoteFanOverride     = false;
uint8_t remoteFanDutyCmd     = 0;

bool   remoteRgbOverride     = false;
bool   remoteRgbEnableCmd    = false;

bool   remoteBuzzerContinuous = false;

// ================= WIFI (NON-BLOCKING + STABLE) =================
unsigned long wifiLastAttempt = 0;
const unsigned long WIFI_RETRY_MS = 3000;
bool wifiStarted = false;
bool serverStarted = false;
bool ipPrinted = false;
wl_status_t lastWifiStatus = WL_IDLE_STATUS;

// ================= UPDATED WEB PAGE (TOAST + CARD COLOR) =================
const char MAIN_page[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>ESP32 Cooling Pad</title>
  <style>
    body { font-family: Arial, sans-serif; background: #0f172a; color: #e5e7eb; margin: 0; padding: 16px; }

    /* Card base */
    .card {
      background:#111827;
      border-radius:12px;
      padding:16px 20px;
      max-width:520px;
      margin:auto;
      box-shadow:0 10px 25px rgba(0,0,0,0.4);
      border: 2px solid rgba(239,68,68,0.55);  /* default = red-ish */
      transition: border-color 250ms ease, box-shadow 250ms ease;
    }

    /* Connected state -> GREEN glow */
    .card.connected {
      border-color: rgba(34,197,94,0.75);
      box-shadow:0 10px 25px rgba(0,0,0,0.4), 0 0 0 3px rgba(34,197,94,0.15);
    }

    /* Not connected -> RED glow */
    .card.disconnected {
      border-color: rgba(239,68,68,0.75);
      box-shadow:0 10px 25px rgba(0,0,0,0.4), 0 0 0 3px rgba(239,68,68,0.12);
    }

    h2 { margin-top:0; }
    .row { display:flex; justify-content:space-between; margin:6px 0; }
    .label { color:#9ca3af; }
    .value { font-weight:bold; }

    button { padding:8px 16px; border:none; border-radius:999px; margin-right:8px; cursor:pointer; font-weight:600; }
    .auto { background:#22c55e; color:#022c22; }
    .manual { background:#3b82f6; color:#e0f2fe; }
    .active { box-shadow:0 0 0 2px #fbbf24; }

    /* Toast */
    .toast {
      position: fixed;
      left: 50%;
      bottom: 18px;
      transform: translateX(-50%) translateY(20px);
      background: rgba(17,24,39,0.96);
      border: 1px solid rgba(148,163,184,0.25);
      color: #e5e7eb;
      padding: 10px 14px;
      border-radius: 999px;
      box-shadow: 0 12px 30px rgba(0,0,0,0.45);
      opacity: 0;
      pointer-events: none;
      transition: opacity 220ms ease, transform 220ms ease;
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 600;
    }
    .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

    .dot { width: 10px; height: 10px; border-radius: 50%; background: #94a3b8; }
    .dot.green { background: #22c55e; }
    .dot.red { background: #ef4444; }
  </style>
</head>
<body>
  <div class="card disconnected" id="card">
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

  <!-- Toast element -->
  <div class="toast" id="toast">
    <span class="dot" id="toastDot"></span>
    <span id="toastText">-</span>
  </div>

<script>
let lastConnected = null;
let toastTimer = null;

function showToast(msg, ok){
  const toast = document.getElementById('toast');
  const dot   = document.getElementById('toastDot');
  const text  = document.getElementById('toastText');

  text.textContent = msg;
  dot.classList.remove('green', 'red');
  dot.classList.add(ok ? 'green' : 'red');

  toast.classList.add('show');

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 1600);
}

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

      // Mode button highlight
      document.getElementById('btnAuto').classList.remove('active');
      document.getElementById('btnManual').classList.remove('active');
      if (d.mode === "AUTO") document.getElementById('btnAuto').classList.add('active');
      else document.getElementById('btnManual').classList.add('active');

      // Card color change
      const card = document.getElementById('card');
      card.classList.remove('connected', 'disconnected');
      card.classList.add(d.connected ? 'connected' : 'disconnected');

      // Toast only on state change
      if (lastConnected === null) {
        lastConnected = d.connected; // first load no toast
      } else if (d.connected !== lastConnected) {
        if (d.connected) showToast("Laptop CONNECTED ✅", true);
        else showToast("Laptop DISCONNECTED ❌", false);
        lastConnected = d.connected;
      }
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
float estimateDistanceCm(int irRaw) {
  int clamped = constrain(irRaw, IR_RAW_FAR, IR_RAW_NEAR);
  long distLong = map(clamped, IR_RAW_NEAR, IR_RAW_FAR, 10, 80);
  return (float)distLong;
}

// ================= ADC READ HELPER =================
int readAdcSmooth(int pin) {
  analogRead(pin);
  delayMicroseconds(50);
  int val = analogRead(pin);
  return val;
}

// ================= LM35 READ HELPER =================
float readLM35TempC() {
  int raw = readAdcSmooth(PIN_LM35);
  float voltage = (raw * 3.3f) / 4095.0f;
  float tempC   = voltage * 100.0f;
  return tempC;
}

// ================= BH1750 HELPERS =================
void bh1750Begin() {
  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(0x01);
  Wire.endTransmission();
  delay(10);
  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(0x10);
  Wire.endTransmission();
}

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

  if (autoMode) {
    remoteFanOverride      = false;
    remoteRgbOverride      = false;
    remoteBuzzerContinuous = false;
  }

  if (autoMode) startBeepPattern(1);
  else          startBeepPattern(2);

  showModeOverlay = true;
  modeOverlayUntil = millis() + MODE_OVERLAY_DURATION;
}

// ================= RGB HELPERS =================
void setAllRgb(bool on) {
  for (int i = 0; i < NUM_RGB; i++) {
    digitalWrite(RGB_PINS[i], on ? HIGH : LOW);
  }
}

void updateRgbChase(bool enabled) {
  if (!enabled) {
    setAllRgb(false);
    return;
  }

  unsigned long now = millis();
  if (now - lastRgbStep >= RGB_INTERVAL) {
    lastRgbStep = now;

    rgbIndex++;
    if (rgbIndex >= NUM_RGB) rgbIndex = 0;

    for (int i = 0; i < NUM_RGB; i++) {
      digitalWrite(RGB_PINS[i], (i == rgbIndex) ? HIGH : LOW);
    }
  }
}

// ================= OLED HELPERS =================
void showStartupAnimation() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_t0_12_tr);
  u8g2.drawStr(15, 32, "Starting System...");
  u8g2.sendBuffer();
  delay(800);
  u8g2.clearBuffer();

  u8g2.setFont(u8g2_font_t0_12_tr);
  for (int x = -128; x <= 10; x += 8) {
    u8g2.clearBuffer();
    u8g2.drawStr(x, 22, "ESP32-Based");
    u8g2.sendBuffer();
    delay(40);
  }
  delay(200);

  for (int x = 128; x >= 10; x -= 8) {
    u8g2.clearBuffer();
    u8g2.drawStr(10, 22, "ESP32-Based");
    u8g2.drawStr(x, 38, "Smart Gaming");
    u8g2.sendBuffer();
    delay(40);
  }
  delay(250);

  for (int i = 0; i < 2; i++) {
    u8g2.clearBuffer();
    u8g2.drawStr(10, 22, "ESP32-Based");
    u8g2.drawStr(10, 38, "Smart Gaming");
    u8g2.drawStr(10, 54, "Laptop Cooling Pad");
    u8g2.sendBuffer();
    delay(220);
  }

  u8g2.clearBuffer();
  u8g2.drawStr(30, 32, "Loading...");
  u8g2.drawFrame(10, 40, 108, 10);
  for (int i = 0; i <= 104; i += 8) {
    u8g2.drawBox(12, 42, i, 6);
    u8g2.sendBuffer();
    delay(80);
  }
  delay(250);
  u8g2.clearBuffer();
}

void drawModeOverlay() {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_logisoso22_tf);
  const char* text = autoMode ? "AUTO" : "MANUAL";
  u8g2.drawStr(10, 40, text);
  u8g2.sendBuffer();
}

void drawAutoModeScreen(float lm35TempC, float dhtTemp, float dhtHum,
                        float distCm, float lux, uint8_t fanDuty) {

  u8g2.clearBuffer();

  u8g2.setFont(u8g2_font_5x7_tr);
  u8g2.drawStr(0, 8, "AUTO MODE");
  u8g2.setCursor(80, 8);
  u8g2.print("F:");
  u8g2.print(fanDuty);

  u8g2.setCursor(0, 20);
  u8g2.print("LM35: ");
  u8g2.print(lm35TempC, 1);
  u8g2.print(" C");

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

  u8g2.setCursor(0, 40);
  u8g2.print("D:");
  u8g2.print(distCm, 0);
  u8g2.print("cm Lx:");
  u8g2.print(lux, 0);

  u8g2.setCursor(0, 52);
  u8g2.print("Status: ");
  if (distCm > 0 && distCm <= 10.0) u8g2.print("CONNECTED");
  else                              u8g2.print("NOT CONNECTED");

  u8g2.sendBuffer();
}

void drawManualModeScreen(float lm35TempC, float dhtTemp, float dhtHum,
                          int potRaw, float lux, uint8_t fanDuty) {

  int fanPercent = map(fanDuty, 0, 255, 0, 100);
  fanPercent = constrain(fanPercent, 0, 100);

  u8g2.clearBuffer();

  u8g2.setFont(u8g2_font_5x7_tr);
  u8g2.drawStr(0, 8, "MANUAL MODE");
  u8g2.setCursor(80, 8);
  u8g2.print("F:");
  u8g2.print(fanDuty);

  u8g2.setCursor(0, 20);
  u8g2.print("LM35: ");
  u8g2.print(lm35TempC, 1);
  u8g2.print(" C");

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

  u8g2.setCursor(0, 40);
  u8g2.print("Fan: ");
  u8g2.print(fanPercent);
  u8g2.print(" %");

  u8g2.setCursor(0, 52);
  u8g2.print("Pot:");
  u8g2.print(potRaw);
  u8g2.print(" Lx:");
  u8g2.print(lux, 0);

  int barX = 0, barY = 58, barWidth = 120, barHeight = 6;
  u8g2.drawFrame(barX, barY, barWidth, barHeight);

  int fillWidth = map(fanPercent, 0, 100, 0, barWidth - 2);
  fillWidth = constrain(fillWidth, 0, barWidth - 2);
  u8g2.drawBox(barX + 1, barY + 1, fillWidth, barHeight - 2);

  int markerX = barX + 1 + fillWidth;
  if (markerX > barX + barWidth - 2) markerX = barX + barWidth - 2;
  if (animState) u8g2.drawLine(markerX, barY + 1, markerX, barY + barHeight - 2);

  u8g2.sendBuffer();
  animState = !animState;
}

// ================= BUTTON HANDLING =================
void handleModeButton() {
  int reading = digitalRead(PIN_BUTTON);

  if (reading != lastButtonRead) lastDebounceTime = millis();

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != buttonState) {
      buttonState = reading;
      if (buttonState == LOW) setMode(!autoMode);
    }
  }
  lastButtonRead = reading;
}

// ================= HTTP HANDLERS =================
void handleRoot() { server.send(200, "text/html", MAIN_page); }

void handleStatus() {
  float dhtT = isnan(g_dhtTemp) ? 0.0 : g_dhtTemp;
  float dhtH = isnan(g_dhtHum) ? 0.0 : g_dhtHum;
  float lux  = (g_lux < 0) ? 0.0 : g_lux;

  String json = "{";
  json += "\"mode\":\""; json += (autoMode ? "AUTO" : "MANUAL"); json += "\",";
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
  if (!server.hasArg("mode")) { server.send(400, "text/plain", "Missing mode param"); return; }
  String m = server.arg("mode"); m.toUpperCase();
  if (m == "AUTO") { setMode(true);  server.send(200, "text/plain", "OK AUTO"); }
  else if (m == "MANUAL") { setMode(false); server.send(200, "text/plain", "OK MANUAL"); }
  else server.send(400, "text/plain", "Unknown mode");
}

void handleFan() {
  if (server.hasArg("release")) {
    remoteFanOverride = false;
    server.send(200, "text/plain", "Fan override released");
    return;
  }
  if (!server.hasArg("duty")) { server.send(400, "text/plain", "Missing duty param (0-255)"); return; }
  int duty = server.arg("duty").toInt();
  duty = constrain(duty, 0, 255);
  remoteFanDutyCmd = (uint8_t)duty;
  remoteFanOverride = true;
  server.send(200, "text/plain", "Fan duty set");
}

void handleRgb() {
  if (server.hasArg("release")) {
    remoteRgbOverride = false;
    server.send(200, "text/plain", "RGB override released");
    return;
  }
  if (!server.hasArg("state")) { server.send(400, "text/plain", "Missing state param (ON/OFF)"); return; }
  String st = server.arg("state"); st.toUpperCase();
  if (st == "ON") { remoteRgbOverride = true; remoteRgbEnableCmd = true;  server.send(200, "text/plain", "RGB ON"); }
  else if (st == "OFF") { remoteRgbOverride = true; remoteRgbEnableCmd = false; server.send(200, "text/plain", "RGB OFF"); }
  else server.send(400, "text/plain", "Unknown state (use ON/OFF)");
}

void handleBuzzerHttp() {
  if (server.hasArg("pattern")) {
    int count = server.arg("pattern").toInt();
    if (count < 1) count = 1;
    remoteBuzzerContinuous = false;
    startBeepPattern(count);
    server.send(200, "text/plain", "Beep pattern started");
    return;
  }

  if (server.hasArg("state")) {
    String st = server.arg("state"); st.toUpperCase();
    if (st == "ON") {
      remoteBuzzerContinuous = true;
      buzzerState = BUZZER_IDLE;
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

// ================= WIFI HELPERS =================
void setupServerIfNeeded() {
  if (serverStarted) return;

  server.on("/",        handleRoot);
  server.on("/status",  handleStatus);
  server.on("/setMode", handleSetMode);
  server.on("/fan",     handleFan);
  server.on("/rgb",     handleRgb);
  server.on("/buzzer",  handleBuzzerHttp);

  server.begin();
  serverStarted = true;
  Serial.println("[HTTP] Server started");
}

void startWiFiIfNeeded() {
  if (wifiStarted) return;

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);      // better stability
  WiFi.disconnect(true, true);
  delay(100);

  Serial.println("\n[WiFi] Starting...");
  Serial.print("[WiFi] SSID: "); Serial.println(WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASS);

  wifiStarted = true;
  wifiLastAttempt = millis();
}

void wifiEnsureConnected() {
  startWiFiIfNeeded();

  wl_status_t st = WiFi.status();

  if (st != lastWifiStatus) {
    Serial.print("[WiFi] status = ");
    Serial.println((int)st);
    lastWifiStatus = st;
  }

  if (st == WL_CONNECTED) {
    if (!ipPrinted) {
      Serial.print("[WiFi] Connected! IP: ");
      Serial.println(WiFi.localIP());
      ipPrinted = true;
    }
    setupServerIfNeeded();
    return;
  }

  unsigned long now = millis();
  if (now - wifiLastAttempt >= WIFI_RETRY_MS) {
    wifiLastAttempt = now;
    ipPrinted = false;
    Serial.println("[WiFi] Retry WiFi.begin()");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\nBooting...");

  Wire.begin(21, 22);

  u8g2.begin();
  showStartupAnimation();

  dht.begin();
  bh1750Begin();

  pinMode(PIN_BUTTON, INPUT_PULLUP);

  pinMode(PIN_LED_AUTO, OUTPUT);
  pinMode(PIN_LED_MAN, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_FAN, OUTPUT);

  for (int i = 0; i < NUM_RGB; i++) {
    pinMode(RGB_PINS[i], OUTPUT);
    digitalWrite(RGB_PINS[i], LOW);
  }

  digitalWrite(PIN_BUZZER, LOW);
  analogWrite(PIN_FAN, 0);
  setAllRgb(false);

  autoMode = true;
  updateModeIndicators();

  // Start WiFi (non-blocking)
  startWiFiIfNeeded();
}

// ================= MAIN LOOP =================
void loop() {
  // keep WiFi stable & print IP when connected
  wifiEnsureConnected();

  // handle web only after server starts
  if (serverStarted) server.handleClient();

  // button
  handleModeButton();

  // sensor timing
  updateDht();
  updateLux();

  // fast sensors
  float lm35TempC = readLM35TempC();
  int   irRaw     = readAdcSmooth(PIN_SHARP_IR);

  int potRaw = lastPotRaw;

  float dhtTemp = dhtTempCached;
  float dhtHum  = dhtHumCached;
  float lux     = luxCached;

  float distCm = estimateDistanceCm(irRaw);

  bool connected     = (distCm > 0 && distCm <= 10.0);
  bool laptopPresent = (distCm > 0 && distCm < 40.0);

  bool overTempAlarm = false;

  if (autoMode) {
    uint8_t fanDuty = 0;

    if (laptopPresent) {
      if (lm35TempC < TEMP_LOW) fanDuty = 0;
      else if (lm35TempC < TEMP_MED) fanDuty = 140;
      else fanDuty = 255;

      if (lm35TempC > TEMP_MAX) overTempAlarm = true;
    } else {
      fanDuty = 0;
    }

    currentFanDuty = fanDuty;
    analogWrite(PIN_FAN, currentFanDuty);

    bool rgbEnable;
    if (remoteRgbOverride) rgbEnable = remoteRgbEnableCmd;
    else rgbEnable = (connected && lux >= 0 && lux < LUX_THRESHOLD);

    updateRgbChase(rgbEnable);

  } else {
    potRaw = analogRead(PIN_POT_FAN);
    lastPotRaw = potRaw;

    uint8_t fanDuty;
    if (remoteFanOverride) fanDuty = remoteFanDutyCmd;
    else fanDuty = map(potRaw, 0, 4095, 0, 255);

    currentFanDuty = fanDuty;
    analogWrite(PIN_FAN, currentFanDuty);

    bool rgbEnable;
    if (remoteRgbOverride) rgbEnable = remoteRgbEnableCmd;
    else rgbEnable = true;

    updateRgbChase(rgbEnable);

    overTempAlarm = false;
  }

  // IR <10cm detection beep
  bool veryNear = (distCm <= 10.0);
  if (veryNear && !lastVeryNear) startBeepPattern(2);
  lastVeryNear = veryNear;

  // buzzer priority
  if (overTempAlarm) {
    remoteBuzzerContinuous = false;
    buzzerState = BUZZER_IDLE;
    digitalWrite(PIN_BUZZER, HIGH);
  } else if (remoteBuzzerContinuous) {
    buzzerState = BUZZER_IDLE;
    digitalWrite(PIN_BUZZER, HIGH);
  } else {
    updateBuzzer();
  }

  // DEBUG SERIAL OUTPUT
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

  // OLED
  if (showModeOverlay && (millis() < modeOverlayUntil)) {
    drawModeOverlay();
  } else {
    showModeOverlay = false;
    if (autoMode) drawAutoModeScreen(lm35TempC, dhtTemp, dhtHum, distCm, lux, currentFanDuty);
    else          drawManualModeScreen(lm35TempC, dhtTemp, dhtHum, potRaw, lux, currentFanDuty);
  }
}
