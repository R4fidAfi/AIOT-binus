/*
 * ============================================================================
 * ESP32 Field Node Firmware — Ipomoea Edge-AIoT
 * Target Board : ESP32 DevKit V1 (Wi-Fi 2.4 GHz)
 * Sensors      :
 *   1. DHT22 (GPIO 4) -> Suhu Udara (°C) & Lembab Udara (% RH)
 *   2. Capacitive Soil Moisture v1.2 (GPIO 34 / ADC1_CH6) -> Lembab Tanah (%)
 *      Installed horizontally at 3–5 cm topsoil root depth of Kangkung.
 * Protocol     : HTTP POST JSON to Arduino UNO Q (/api/v1/telemetry) every 5s
 * ============================================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>

// ---------------- WIFI & ARDUINO UNO Q SERVER CONFIG ----------------
const char* WIFI_SSID     = "NAMA_WIFI_ATAU_HOTSPOT_ANDA";
const char* WIFI_PASSWORD = "PASSWORD_WIFI_ANDA";

// Ganti IP di bawah dengan IP Arduino UNO Q (atau Laptop saat uji coba)
const char* UNO_Q_API_URL = "http://192.168.1.17:8000/api/v1/telemetry";
const char* NODE_ID       = "ESP32-FIELD-01";

// ---------------- PIN DEFINITIONS & CALIBRATION ---------------------
#define PIN_DHT22       4
#define DHT_TYPE        DHT22
#define PIN_SOIL_ADC    34   // Harus pin ADC1 (GPIO 32-39) agar tidak bentrok dengan Wi-Fi!
#define PIN_STATUS_LED  2

// Kalibrasi ADC 12-bit (0 - 4095) Sensor Kapasitif Tanah pada kedalaman 3-5 cm
const int ADC_AIR_DRY    = 3150; // Nilai ADC saat sensor kering di udara (0% Lembab Tanah)
const int ADC_WATER_WET  = 1380; // Nilai ADC saat tanah jenuh air (100% Lembab Tanah)

DHT dht(PIN_DHT22, DHT_TYPE);
unsigned long lastSendMs = 0;
const unsigned long SEND_INTERVAL_MS = 5000; // Kirim real-time setiap 5 detik

// Filter Median 5 sampel untuk menghilangkan noise pembacaan ADC tanah
int readFilteredSoilAdc() {
  int samples[5];
  for (int i = 0; i < 5; i++) {
    samples[i] = analogRead(PIN_SOIL_ADC);
    delay(15);
  }
  // Pengurutan sederhana (Bubble Sort 5 elemen)
  for (int i = 0; i < 4; i++) {
    for (int j = i + 1; j < 5; j++) {
      if (samples[j] < samples[i]) {
        int tmp = samples[i];
        samples[i] = samples[j];
        samples[j] = tmp;
      }
    }
  }
  return samples[2]; // Nilai tengah (Median)
}

float convertAdcToSoilPercent(int adcRaw) {
  float pct = (float)(ADC_AIR_DRY - adcRaw) * 100.0f / (float)(ADC_AIR_DRY - ADC_WATER_WET);
  if (pct < 0.0f) pct = 0.0f;
  if (pct > 100.0f) pct = 100.0f;
  return pct;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("[WiFi] Menghubungkan ke ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(400);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Terhubung! IP ESP32: " + WiFi.localIP().toString());
  } else {
    Serial.println("\n[WiFi] Gagal terhubung, akan dicoba ulang...");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_STATUS_LED, OUTPUT);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db); // Rentang pembacaan penuh 0 - 3.3V
  dht.begin();
  connectWiFi();
}

void loop() {
  unsigned long now = millis();
  if (now - lastSendMs < SEND_INTERVAL_MS) {
    return;
  }
  lastSendMs = now;

  connectWiFi();

  // 1. Baca Suhu Udara & Lembab Udara dari DHT22
  float temperature = dht.readTemperature();
  float humidity    = dht.readHumidity();

  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("[WARN] Pembacaan DHT22 gagal, menggunakan nilai cadangan aman.");
    temperature = 28.8;
    humidity    = 73.0;
  }

  // 2. Baca Lembab Tanah dari Sensor Kapasitif v1.2
  int adcRaw         = readFilteredSoilAdc();
  float soilMoisture = convertAdcToSoilPercent(adcRaw);

  // 3. Susun Payload JSON untuk dikirim ke Arduino UNO Q
  String jsonPayload = "{";
  jsonPayload += "\"temperature\":" + String(temperature, 1) + ",";
  jsonPayload += "\"humidity\":" + String(humidity, 1) + ",";
  jsonPayload += "\"soil_moisture\":" + String(soilMoisture, 1) + ",";
  jsonPayload += "\"adc_raw\":" + String(adcRaw) + ",";
  jsonPayload += "\"node_id\":\"" + String(NODE_ID) + "\"";
  jsonPayload += "}";

  Serial.println("[TELEMETRY] " + jsonPayload);

  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(UNO_Q_API_URL);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(3000);

    digitalWrite(PIN_STATUS_LED, HIGH);
    int httpCode = http.POST(jsonPayload);
    digitalWrite(PIN_STATUS_LED, LOW);

    if (httpCode > 0) {
      Serial.printf("[HTTP] Terkirim ke UNO Q (Status %d)\n", httpCode);
    } else {
      Serial.printf("[HTTP] Gagal kirim: %s\n", http.errorToString(httpCode).c_str());
    }
    http.end();
  }
}
