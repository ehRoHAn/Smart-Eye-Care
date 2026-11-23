# Smart Eye-Care Guard

A hardware and software based system that protects your eyes by dimming the screen when you sit too close.

## How it works
- An ultrasonic sensor (Arduino Nano) measures your distance from the screen.
- The webcam confirms a real face is present (OpenCV), so objects don't trigger it.
- Beyond 42 cm: normal brightness. 42 to 30 cm: brightness drops. Under 30 cm: minimum brightness and a buzzer. Under 20 cm: warm light filter.

## Files
- `eye_guard.ino`: Arduino Nano code (sensor, buzzer, OLED)
- `eye_care_daemon.py`: PC app (face detection, brightness control)
- `requirements.txt`: Python libraries

## Hardware
Arduino Nano, HC-SR04 ultrasonic sensor, buzzer, OLED display

## Run
1. Upload `eye_guard.ino` to the Arduino Nano.
2. `pip install -r requirements.txt`
3. `python eye_care_daemon.py`

## Download
A ready-to-run Windows app (no Python needed) is available on the Releases page. The Arduino hardware with `eye_guard.ino` uploaded is still required.
