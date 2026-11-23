/*
 * Smart Eye-Care Guard v5 (sensor + camera face check)
 * Sensor distance mape. Camera (PC) bole face ache kina.
 * Face na thakle sob kichu SAFE dhora hoy.
 * 42cm+ = SAFE | 42-30cm = NEAR | <=30cm = CLOSE (buzzer)
 * <20cm warm light = Python-e hoy
 */
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

const int trigPin   = 9;
const int echoPin   = 10;
const int buzzerPin = 8;     // OLED: SDA = A4, SCL = A5

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDR 0x3C
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
bool oledOK = false;

const int SAFE_DIST  = 42;
const int CLOSE_DIST = 30;
const int FAST_DIST  = 15;
const int GAP_SLOW   = 1000;
const int GAP_FAST   = 80;
const int BEEP_LEN   = 40;

const unsigned long MEASURE_INTERVAL = 60;
const unsigned long DISPLAY_INTERVAL = 150;
const unsigned long SEND_INTERVAL    = 100;
const unsigned long PC_TIMEOUT       = 2000;  // PC theke khobor na ashle sensor-only mode

int readings[3] = {999, 999, 999};
byte readIdx = 0;
int distance = 999;

bool faceOK = true;
unsigned long lastFaceMsg = 0;
char rxBuf[8];
byte rxN = 0;

bool buzzerOn = false;
unsigned long lastBeep = 0, lastMeasure = 0, lastDisplay = 0, lastSend = 0;

int measureDistance() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duration = pulseIn(echoPin, HIGH, 30000UL);
  if (duration == 0) return 999;
  return (int)(duration * 0.0343 / 2);
}

int median3(int a, int b, int c) {
  if ((a >= b && a <= c) || (a <= b && a >= c)) return a;
  if ((b >= a && b <= c) || (b <= a && b >= c)) return b;
  return c;
}

// PC theke "F:1" (face ache) ba "F:0" (face nai) pore
void readPC(unsigned long now) {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      rxBuf[rxN] = 0;
      if (rxBuf[0] == 'F' && rxBuf[1] == ':') {
        faceOK = (rxBuf[2] == '1');
        lastFaceMsg = now;
      }
      rxN = 0;
    } else if (c != '\r' && rxN < sizeof(rxBuf) - 1) {
      rxBuf[rxN++] = c;
    }
  }
}

bool pcAlive(unsigned long now) {
  return lastFaceMsg != 0 && (now - lastFaceMsg) < PC_TIMEOUT;
}

// PC (EyeCare.exe) na thakle ba face na thakle 999 (SAFE, buzzer chup)
int effectiveDistance(unsigned long now) {
  if (!pcAlive(now)) return 999;
  if (!faceOK) return 999;
  return distance;
}

void updateBuzzer(unsigned long now) {
  int dist = effectiveDistance(now);
  if (dist > 0 && dist <= CLOSE_DIST) {
    int d = constrain(dist, FAST_DIST, CLOSE_DIST);
    unsigned long gap = map(d, FAST_DIST, CLOSE_DIST, GAP_FAST, GAP_SLOW);
    if (!buzzerOn && now - lastBeep >= gap) {
      digitalWrite(buzzerPin, HIGH);
      buzzerOn = true;
      lastBeep = now;
    }
  }
  if (buzzerOn && now - lastBeep >= BEEP_LEN) {
    digitalWrite(buzzerPin, LOW);
    buzzerOn = false;
  }
}

void drawDisplay(unsigned long now) {
  int dist = effectiveDistance(now);
  bool noPC   = !pcAlive(now);
  bool noFace = pcAlive(now) && !faceOK;

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print(F("EYE-CARE GUARD"));

  display.setTextSize(3);
  display.setCursor(0, 14);
  if (distance >= 400) display.print(F("--"));
  else display.print(distance);
  display.setTextSize(1);
  display.print(F(" cm"));

  display.setTextSize(2);
  display.setCursor(0, 42);
  if (noPC)                        display.print(F("NO PC"));
  else if (noFace)                 display.print(F("NO FACE"));
  else if (dist <= CLOSE_DIST)     display.print(F("CLOSE!"));
  else if (dist < SAFE_DIST)       display.print(F("NEAR"));
  else                             display.print(F("SAFE"));

  display.drawRect(0, 60, 128, 4, SSD1306_WHITE);
  if (dist < SAFE_DIST) {
    int d = constrain(dist, CLOSE_DIST, SAFE_DIST);
    int w = map(d, SAFE_DIST, CLOSE_DIST, 0, 128);
    display.fillRect(0, 60, w, 4, SSD1306_WHITE);
  }
  display.display();
}

void setup() {
  Serial.begin(9600);
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(buzzerPin, OUTPUT);
  digitalWrite(buzzerPin, LOW);

  oledOK = display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  if (oledOK) {
    Wire.setClock(400000);
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);
    display.setCursor(0, 24);
    display.print(F("Eye-Care Guard ready"));
    display.display();
    delay(800);
  }
}

void loop() {
  unsigned long now = millis();

  readPC(now);

  if (now - lastMeasure >= MEASURE_INTERVAL) {
    lastMeasure = now;
    readings[readIdx] = measureDistance();
    readIdx = (readIdx + 1) % 3;
    distance = median3(readings[0], readings[1], readings[2]);
  }

  updateBuzzer(now);

  if (oledOK && now - lastDisplay >= DISPLAY_INTERVAL) {
    lastDisplay = now;
    drawDisplay(now);
  }

  if (now - lastSend >= SEND_INTERVAL) {
    lastSend = now;
    Serial.print(F("DIST:"));
    Serial.println(distance);
  }
}