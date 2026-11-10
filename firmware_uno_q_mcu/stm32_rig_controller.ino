python uji_webcam.py 1/*
 * ============================================================================
 * Arduino UNO Q — STM32U585 Real-Time MCU Co-Processor Firmware
 * Controls:
 *   - Pin D3 (PWM Output -> Gate MOSFET IRLZ44N / 2N7000) : Lampu LED Diffuser Ring 5V
 *   - Pin D2 (Input Pull-up)                             : Tombol Fisik Pemicu Kamera
 *   - Pin D13 (Built-in LED)                             : Indikator Status Aktif
 * Synchronizes with Python FastAPI Backend on Qualcomm Dragonwing QRB2210 via Serial/IPC.
 * ============================================================================
 */

#define PIN_TRIGGER_BTN  2
#define PIN_LED_RING_PWM 3
#define PIN_STATUS_LED   13

int currentPwm = 0;
bool ledState  = false;
unsigned long lastDebounceMs = 0;
const unsigned long DEBOUNCE_DELAY_MS = 250;

void setLedRingHardware(bool turnOn, int pwmVal) {
  ledState = turnOn;
  currentPwm = turnOn ? constrain(pwmVal, 0, 255) : 0;
  analogWrite(PIN_LED_RING_PWM, currentPwm);
  digitalWrite(PIN_STATUS_LED, turnOn ? HIGH : LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIGGER_BTN, INPUT_PULLUP);
  pinMode(PIN_LED_RING_PWM, OUTPUT);
  pinMode(PIN_STATUS_LED, OUTPUT);

  // Pastikan lampu kamera mati saat awal standby (Hemat daya & dingin)
  setLedRingHardware(false, 0);
  Serial.println("{\"mcu\":\"STM32U585_READY\",\"led_on\":false}");
}

void loop() {
  // 1. Baca perintah dari Prosesor Linux QRB2210 (misal saat klik "Nyalakan Kamera" / "Ambil Foto")
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.startsWith("LED_ON")) {
      int pwm = 225;
      int sep = cmd.indexOf(':');
      if (sep > 0) {
        pwm = cmd.substring(sep + 1).toInt();
      }
      setLedRingHardware(true, pwm);
      Serial.print("{\"status\":\"LED_ON\",\"pwm\":");
      Serial.print(currentPwm);
      Serial.println("}");
    } else if (cmd.startsWith("LED_OFF")) {
      setLedRingHardware(false, 0);
      Serial.println("{\"status\":\"LED_OFF\",\"pwm\":0}");
    }
  }

  // 2. Deteksi jika tombol fisik pada rig (Pin D2) ditekan oleh pengguna
  if (digitalRead(PIN_TRIGGER_BTN) == LOW) {
    unsigned long now = millis();
    if (now - lastDebounceMs > DEBOUNCE_DELAY_MS) {
      lastDebounceMs = now;
      Serial.println("{\"event\":\"PHYSICAL_BUTTON_PRESSED\"}");
    }
  }
}
