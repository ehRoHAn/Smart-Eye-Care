# eye_care_daemon.py (v5: sensor distance + camera face check)
import ctypes
import os
import sys
import serial
import time
import cv2
import screen_brightness_control as sbc

PORT = 'COM6'          # fallback; normally Arduino-r port auto-detect hoy
BAUD_RATE = 9600
CAM_INDEX = 0
SHOW_PREVIEW = False   # False = kono window dekhabe na, shob background-e cholbe
RETRY_EVERY = 3      

BRIGHT_START_DIST = 42   
MIN_DIST          = 30   
WARM_DIST         = 20   
MIN_BRIGHTNESS    = 35

FACE_GRACE = 1.5         # face haralew 1.5 sec "face ache" dhora hobe
CLOSE_FACE_HOLD = 4.0    

CLOSE_FACE_RATIO = 0.35  # hold shudhu tokhon, jokhon last dekha face frame-er 35%+ chowra chilo (mane apni kache chilen)
CONFIRM_FRAMES = 3       # porpor 3 frame-e face dekhle tobei face dhora hobe (fake ek-frame box bad)
MIN_FRAME_LIGHT = 30     # frame-er gorosori brightness eto-r kom hole (camera dhaka/dark) face khoja hobe na

DETECT_SCALE  = 0.75     # 1.0 = full size (beshi accurate, ektu slow)
SCALE_FACTOR  = 1.1
MIN_NEIGHBORS = 6       
MIN_FACE_SIZE = 70       # choto fake box (deyal, kapor) ignore korar jonno
SEND_EVERY = 0.1         

TINT_R, TINT_G, TINT_B = 1.0, 0.85, 0.55

def set_color_tint(r, g, b):
    try:
        gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        ramp = ((ctypes.c_ushort * 256) * 3)()
        for i in range(256):
            base = i * 256
            ramp[0][i] = min(65535, int(base * r))
            ramp[1][i] = min(65535, int(base * g))
            ramp[2][i] = min(65535, int(base * b))
        hdc = user32.GetDC(0)
        ok = gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        user32.ReleaseDC(0, hdc)
        return bool(ok)
    except Exception as err:
        print(f"[WARN] Tint failed: {err}")
        return False

def tint_on():
    set_color_tint(TINT_R, TINT_G, TINT_B)

def tint_off():
    set_color_tint(1.0, 1.0, 1.0)

def compute_brightness(distance, original):
    if distance >= BRIGHT_START_DIST:
        return original
    if distance <= MIN_DIST:
        return MIN_BRIGHTNESS
    ratio = (distance - MIN_DIST) / (BRIGHT_START_DIST - MIN_DIST)
    return int(MIN_BRIGHTNESS + ratio * (original - MIN_BRIGHTNESS))

def candidate_ports():
    """Arduino-r moto port gulo age, tarpor baki shob, tarpor fallback PORT."""
    ports = []
    try:
        from serial.tools import list_ports
        all_ports = list(list_ports.comports())
        keys = ("arduino", "ch340", "ch341", "usb serial", "cp210", "ftdi", "usb-serial")
        likely = [p.device for p in all_ports
                  if any(k in f"{p.description} {p.manufacturer}".lower() for k in keys)]
        rest = [p.device for p in all_ports if p.device not in likely]
        ports = likely + rest
    except Exception:
        pass
    if PORT not in ports:
        ports.append(PORT)
    return ports

def open_arduino():
    """Port khole 5 sec-er moddhe 'DIST:' line ashe kina dekhe. Na ashle oita Arduino na
    (jemon Bluetooth COM port), bondho kore porer port-e jay."""
    for port in candidate_ports():
        ser = None
        try:
            ser = serial.Serial(port, BAUD_RATE, timeout=0.05)
            deadline = time.time() + 5   # Arduino reset hoye boot hoyar shomoy-o ei 5 sec-er moddhe
            buf = ""
            while time.time() < deadline:
                buf += ser.read(ser.in_waiting or 1).decode('utf-8', errors='ignore')
                if "DIST:" in buf and "\n" in buf.split("DIST:", 1)[1]:
                    ser.timeout = 0.01
                    print(f"[INIT] Arduino connected on {port}")
                    return ser
            print(f"[INIT] {port} No data comes from Arduino,skip")
            ser.close()
        except Exception:
            try:
                if ser is not None:
                    ser.close()
            except Exception:
                pass
            continue
    print("[ERROR] Arduino paoa jayni (USB lagano ache kina dekhun)")
    return None

def setup_logging():
    """Console na thakle (noconsole .exe) output EyeCare_log.txt te lekha hoy."""
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                               else os.path.abspath(__file__))
        try:
            log = open(os.path.join(base, "EyeCare_log.txt"), "a", buffering=1, encoding="utf-8")
            sys.stdout = log
            sys.stderr = log
            print(f"\n===== Start {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
        except Exception:
            pass

def already_running():
    """Duita EyeCare ek shathe chalu hole dwitiyota bondho hoye jabe (COM port clash er jonno)."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "EyeCareGuardSingleInstance")
        already_running.handle = handle   # reference rakhi, noile mutex chole jay
        return kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return False

def main():
    ser = open_arduino()
    if ser is None:
        return None

    cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[ERROR] Camera open hocche na")
        ser.close()
        return None

    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    try:
        levels = sbc.get_brightness()
        original_brightness = levels[0] if isinstance(levels, list) else levels
    except Exception:
        original_brightness = 75
    print(f"[SYSTEM] Baseline brightness: {original_brightness}%")

    last_applied = original_brightness
    warm_on = False
    sensor_dist = 999
    last_face_time = 0.0
    last_sent = 0.0
    last_face_state = None
    rx = ""
    last_dist_time = time.time()
    face_streak = 0
    last_face_big = False
    quit_requested = False

    try:
        while True:
            now = time.time()

            # 1) camera: face ache kina
            ok, frame = cap.read()
            faces = []
            if ok:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if DETECT_SCALE != 1.0:
                    gray = cv2.resize(gray, (0, 0), fx=DETECT_SCALE, fy=DETECT_SCALE)
                if gray.mean() >= MIN_FRAME_LIGHT:   # camera dhaka/dark hole face khuji na
                    gray = cv2.equalizeHist(gray)    # alo kom hole help kore
                    faces = cascade.detectMultiScale(
                        gray, scaleFactor=SCALE_FACTOR, minNeighbors=MIN_NEIGHBORS,
                        minSize=(MIN_FACE_SIZE, MIN_FACE_SIZE))
                    if len(faces) > 1:
                        # shudhu shobcheye boro face rakhi (ekta person-er ekta-i face)
                        faces = [max(faces, key=lambda f: f[2] * f[3])]
            else:
                gray = None

            if len(faces) > 0:
                face_streak += 1
                if face_streak >= CONFIRM_FRAMES:
                    last_face_time = now
                    last_face_big = (faces[0][2] / gray.shape[1]) >= CLOSE_FACE_RATIO
            else:
                face_streak = 0

            # face ache dhora hobe jodi: (a) shomproti face dekha gese, ba
            # (b) apni khub kache chilen (boro face dekha giyechilo), sensor ekhon-o 42cm-er bhitore
            seen_recently = (now - last_face_time) <= FACE_GRACE
            too_close_hold = (sensor_dist < BRIGHT_START_DIST and last_face_big and
                              (now - last_face_time) <= CLOSE_FACE_HOLD)
            face_present = seen_recently or too_close_hold

            # 2) Arduino-ke face status pathao
            if now - last_sent >= SEND_EVERY:
                ser.write(b"F:1\n" if face_present else b"F:0\n")
                last_sent = now

            # 3) Arduino theke sensor distance pore nao
            data = ser.read(ser.in_waiting or 1).decode('utf-8', errors='ignore')
            if data:
                rx += data
                while "\n" in rx:
                    line, rx = rx.split("\n", 1)
                    line = line.strip()
                    if line.startswith("DIST:"):
                        try:
                            sensor_dist = int(line.split(":")[1])
                            last_dist_time = now
                        except ValueError:
                            pass

            # 10 sec Arduino theke kichu na ashle (USB khule gese ba atke gese) abar notun kore connect
            if now - last_dist_time > 10:
                print("[WARN] Arduino-r data ashche na, abar connect korchi...")
                break

            # 4) face na thakle SAFE (999), face thakle sensor distance
            distance = sensor_dist if face_present else 999

            target = compute_brightness(distance, original_brightness)
            if abs(target - last_applied) >= 2:
                sbc.set_brightness(target)
                last_applied = target
                print(f"[BRIGHTNESS] {distance}cm -> {target}%")

            should_warm = distance < WARM_DIST
            if should_warm != warm_on:
                if should_warm:
                    tint_on()
                    print("[WARM LIGHT] ON")
                else:
                    tint_off()
                    print("[WARM LIGHT] OFF")
                warm_on = should_warm

            if face_present != last_face_state:
                print(f"[FACE] {'detected' if face_present else 'lost'}")
                last_face_state = face_present

            # 5) preview
            if SHOW_PREVIEW and ok:
                inv = 1.0 / DETECT_SCALE
                for (x, y, w, h) in faces:
                    cv2.rectangle(frame,
                                  (int(x * inv), int(y * inv)),
                                  (int((x + w) * inv), int((y + h) * inv)),
                                  (0, 255, 0), 2)
                cv2.putText(frame, f"sensor: {sensor_dist}cm  face: {face_present}",
                            (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                cv2.imshow("Eye-Care (q=quit)", frame)
                if (cv2.waitKey(1) & 0xFF) == ord('q'):
                    quit_requested = True
                    break
            elif not SHOW_PREVIEW:
                time.sleep(0.02)
    except KeyboardInterrupt:
        print("\n[TERMINATING] Restoring settings...")
        quit_requested = True
    finally:
        try:
            sbc.set_brightness(original_brightness)
        except Exception:
            pass
        tint_off()
        cap.release()
        cv2.destroyAllWindows()
        try:
            ser.close()
        except Exception:
            pass
    return "quit" if quit_requested else None

if __name__ == '__main__':
    setup_logging()
    if already_running():
        sys.exit(0)
    # kono error hole (Arduino khule gele, camera busy etc.) bondho na hoye abar chesta kore
    while True:
        try:
            result = main()
        except Exception as err:
            print(f"[ERROR] {err}")
            result = None
        if result == "quit":
            break
        time.sleep(RETRY_EVERY)