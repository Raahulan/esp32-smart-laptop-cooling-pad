<h1 align="center" style="font-size:44px;">
  ESP32 Smart Power Cooling Pad for Gaming Laptop
</h1>

<p align="center">
  <b>Wi-Fi Connected • Arduino Firmware • Python Dashboard • Smart Fan Control</b>
</p>

<p align="center">
  <i>Project Prototype</i>
</p>

<p align="center">
  <!-- BIG PROTOTYPE IMAGE (Uploaded inside: Updated Images/Prototype.jpeg) -->
  <img src="Updated Images/Prototype.jpeg" width="900" alt="ESP32 Smart Cooling Pad Prototype"/>
</p>

<p align="center">
  <sub><b>ESP32-based thermal management system with real-time monitoring and control via Python Dashboard.</b></sub>
</p>

---

## 🔍 Overview
This project is a **Wi-Fi enabled smart cooling pad** designed for **gaming and high-performance laptops**.
An **ESP32** controls external cooling fans based on real-time temperature readings and communicates
with a **Python-based desktop dashboard** over Wi-Fi for monitoring and control.

The system supports both **automatic temperature-based control** and **manual user control**,
making it suitable for smart thermal management applications.

---

## ✨ Features
- ESP32 firmware developed using Arduino  
- Wi-Fi communication between ESP32 and Python UI  
- Python dashboard for:
  - real-time temperature monitoring  
  - fan duty / ON-OFF status  
  - AUTO / MANUAL mode selection  
- Temperature threshold-based automatic fan control  
- Manual control through potentiometer / GUI  
- Modular and expandable design  

---

## 🧰 Hardware Components
- ESP32 DevKit  
- DC cooling fan + driver (MOSFET / Relay)  
- Sensors (used in this project):
  - **LM35** (Analog temperature)
  - **Sharp IR** (Analog distance / presence)
  - **Potentiometer** (Analog manual fan input)
- (Optional) DHT22 for ambient temperature & humidity  
- OLED (SH1106) display (optional)  
- External power supply (5V / 12V based on fan)  

---

## 🖥️ Software Stack

### Firmware
- Arduino IDE / PlatformIO  
- ESP32 Board Support Package  
- Libraries: `WiFi.h`, `WebServer.h`, `Wire.h`, `U8g2lib.h`, `DHT.h` (optional)

### Dashboard
- Python 3.x  
- UI Framework: Tkinter  
- Libraries:
  - `requests`
  - `matplotlib`
  - `threading`, `queue`
  - `socket`, `ipaddress`

---

## 🌐 Wi-Fi Communication
The ESP32 communicates with the Python dashboard over Wi-Fi using **HTTP REST API**.

### Typical Endpoints
- `/status`  → read sensor values + mode
- `/setMode` → set AUTO / MANUAL
- `/fan`     → set PWM duty (manual)
- `/rgb` / `/buzzer` → optional controls

---

## ⚙️ System Working
1. ESP32 connects to the configured Wi-Fi network  
2. Sensors continuously measure temperature/distance/manual input  
3. ESP32 applies control logic:
   - **AUTO mode:** fan adjusts based on temperature thresholds  
   - **MANUAL mode:** user sets fan duty using GUI/potentiometer  
4. Python dashboard polls `/status` and displays:
   - readings, mode, fan duty
   - live graphs
5. User can control the system from the GUI  

---

## 🖼️ Project Images & Screenshots

### 🔹 Prototype Views (Optional)
> If these images exist inside `images/` folder, they will show.
<p align="center">
  <img src="images/front_view.jpg" width="420" alt="Front View"/>
  <img src="images/back_view.jpg" width="420" alt="Back View"/>
</p>
<p align="center">
  <sub>Front and back view of the cooling pad prototype</sub>
</p>

### 🔹 Device Setup & Python Dashboard
<p align="center">
  <img src="images/cooling_pad_setup.jpg" width="420" alt="Cooling Pad Setup"/>
  <img src="images/dashboard_ui.png" width="420" alt="Python Dashboard UI"/>
</p>

### 🔹 Breadboard / Wiring Check
<p align="center">
  <img src="images/breadboard_check.jpg" width="820" alt="Breadboard Check"/>
</p>

### 🔹 Wi-Fi Connection Status
<p align="center">
  <img src="images/wifi_status.jpg" width="820" alt="Wi-Fi Status Check"/>
</p>

### 🔹 Sensor Images (from report images)
> Use these only if you uploaded them to GitHub.  
> (You can keep them in `images/` or in `Updated Images/`.)

<p align="center">
  <img src="images/LM-35 Temperature-sensor.jpeg" width="270" alt="LM35 Sensor"/>
  <img src="images/Sharp-IR sensor.jpeg" width="270" alt="Sharp IR Sensor"/>
  <img src="images/Potentiometer for Cooling-Fan.jpeg" width="270" alt="Potentiometer"/>
</p>

> If you placed them inside **Updated Images** folder instead, use this block:
<p align="center">
  <img src="Updated Images/LM-35 Temperature-sensor.jpeg" width="270" alt="LM35 Sensor"/>
  <img src="Updated Images/Sharp-IR sensor.jpeg" width="270" alt="Sharp IR Sensor"/>
  <img src="Updated Images/Potentiometer for Cooling-Fan.jpeg" width="270" alt="Potentiometer"/>
</p>

---

## 📂 Repository Structure
```text
firmware_arduino/      → ESP32 Arduino firmware
python_dashboard/      → Python GUI dashboard
images/                → Project images & screenshots
Updated Images/        → Updated images (Prototype.jpeg etc.)
README.md
