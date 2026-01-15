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
  <!-- BIG PROTOTYPE IMAGE -->
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

## 🧩 PCB Design & Implementation

### 🔹 PCB 3D View
<p align="center">
  <img src="Updated Images/3D-PCB.png" width="420" alt="PCB 3D View"/>
  <img src="Updated Images/PCB_3D_View.png" width="420" alt="PCB 3D View Angle"/>
</p>
<p align="center">
  <sub>3D render views of the custom ESP32 cooling pad controller PCB</sub>
</p>

---

### 🔹 PCB Top and Bottom Layers
<p align="center">
  <img src="Updated Images/PCB_Top_Layer.png" width="420" alt="PCB Top Layer"/>
  <img src="Updated Images/PCB_Bottom_Layer.png" width="420" alt="PCB Bottom Layer"/>
</p>
<p align="center">
  <sub>PCB routing layers (Top and Bottom)</sub>
</p>

---

### 🔹 PCB Schematic
<p align="center">
  <img src="Updated Images/PCB-Schematic.png" width="850" alt="PCB Schematic"/>
</p>
<p align="center">
  <sub>Full schematic diagram used for the PCB design</sub>
</p>

---

### 🔹 Design Screenshots / CAD Proof
<p align="center">
  <img src="Updated Images/Screenshot 2026-01-15 181153.png" width="420" alt="PCB Screenshot 1"/>
  <img src="Updated Images/Screenshot 2026-01-15 181213.png" width="420" alt="PCB Screenshot 2"/>
</p>

<p align="center">
  <img src="Updated Images/Screenshot 2026-01-15 181247.png" width="420" alt="PCB Screenshot 3"/>
  <img src="Updated Images/Screenshot 2026-01-15 181316.png" width="420" alt="PCB Screenshot 4"/>
</p>

<p align="center">
  <img src="Updated Images/Screenshot 2026-01-15 181825.png" width="850" alt="PCB Screenshot 5"/>
</p>
<p align="center">
  <sub>PCB design and verification screenshots</sub>
</p>

---

## 🖼️ Project Images & Screenshots

### 🔹 Prototype Views (Optional)
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
Updated Images/        → Updated images (Prototype.jpeg, PCB images, etc.)
README.md
