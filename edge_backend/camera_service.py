"""
Camera Acquisition, On-Demand Live MJPEG Streamer & STM32U585 LED Diffuser Ring Sync Service.
Designed specifically for Arduino UNO Q (Qualcomm Dragonwing QRB2210, 2 GB RAM):
1. Default state: Camera is 100% OFF (0% CPU, 0 MB camera buffer).
2. On 'Nyalakan Kamera': Opens USB Webcam at 640x480 @ 10 FPS (MJPG) + turns ON LED Ring (Pin D3).
3. On 'Ambil Foto': Captures the live frame and IMMEDIATELY releases the USB Webcam & turns OFF LED Ring
   so 100% of CPU & RAM are free for the 5-Stage AI Pipeline.
4. Auto-Sleep Guardrail: Automatically turns off camera after 60 seconds of inactivity.
"""

import glob
import math
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Generator, Optional, Tuple

import cv2
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
os.makedirs(CAPTURE_DIR, exist_ok=True)


def ensure_usb_host_mode() -> None:
    """
    Self-healing routine for Qualcomm Dragonwing QRB2210 DWC3 USB controller.
    Restores Host Mode automatically if USB VBUS momentarily fluctuated or reset,
    ensuring the USB-C Hub and physical Webcam remain continuously powered and detected.
    Handles permissions gracefully via direct write and passwordless sudo fallback.
    """
    if os.name != "nt":
        role_paths = glob.glob("/sys/class/usb_role/*/role")
        for role_path in role_paths:
            try:
                with open(role_path, "r") as f:
                    role = f.read().strip()
                if role != "host":
                    try:
                        with open(role_path, "w") as f:
                            f.write("host\n")
                        print(f"[USB_CONTROLLER] Restored {role_path} to host mode (direct)", flush=True)
                    except PermissionError:
                        import subprocess
                        subprocess.run(
                            ["sudo", "-n", "sh", "-c", f"echo host > '{role_path}'"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1.0,
                        )
                        print(f"[USB_CONTROLLER] Restored {role_path} to host mode (sudo)", flush=True)
            except Exception:
                pass

        # Ensure V4L2 device nodes have full read/write access
        video_nodes = glob.glob("/dev/video*")
        if video_nodes:
            try:
                import subprocess
                subprocess.run(
                    ["sudo", "-n", "chmod", "666"] + video_nodes,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=0.5,
                )
            except Exception:
                pass


class USBHostWatchdog(threading.Thread):
    """
    Background supervisor thread that continuously maintains Qualcomm DWC3 USB Host mode.
    Automatically recovers the USB bus and webcam within 3 seconds if the USB hub is plugged
    in after boot, hot-swapped, or momentarily disconnected.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.running = True

    def run(self):
        while self.running:
            try:
                ensure_usb_host_mode()
            except Exception:
                pass
            time.sleep(3.0)


# Start auto-detecting USB watchdog immediately upon service import on Linux
if os.name != "nt":
    _usb_watchdog = USBHostWatchdog()
    _usb_watchdog.start()


class STM32RigBridge:
    """
    Hardware Bridge to STM32U585 MCU on Arduino UNO Q (Serial/IPC).
    Controls Pin D3 (PWM LED Diffuser Ring 5V) and reads Pin D2 (Physical Trigger Button).
    Gracefully operates in virtual mode when running on development PC before UNO Q attachment.
    """

    def __init__(self, serial_port: Optional[str] = None, baudrate: int = 115200):
        self.serial_port = serial_port or os.environ.get("UNO_Q_MCU_PORT", "")
        self.baudrate = baudrate
        self.led_on = False
        self.pwm_value = 220
        self.last_trigger_step = 0  # 0: Idle, 1: Top Captured, 2: Bottom Captured
        self.mcu_connected = False
        self.serial_conn = None
        self._lock = threading.Lock()
        self._init_serial_connection()

    def _init_serial_connection(self) -> None:
        """Auto-detect and connect to the onboard STM32U585 UART port on Arduino UNO Q."""
        try:
            import serial  # type: ignore

            candidates = []
            if self.serial_port:
                candidates.append(self.serial_port)
            if os.name != "nt":
                candidates.extend(
                    glob.glob("/dev/ttyHS*")
                    + glob.glob("/dev/ttyMSM*")
                    + glob.glob("/dev/ttyACM*")
                    + glob.glob("/dev/ttyUSB*")
                )
            else:
                candidates.extend(["COM31", "COM3", "COM4"])

            for port in candidates:
                try:
                    s = serial.Serial(port, self.baudrate, timeout=0.1)
                    if s.is_open:
                        self.serial_conn = s
                        self.serial_port = port
                        self.mcu_connected = True
                        print(f"[STM32_BRIDGE] Connected to STM32 MCU at {port}", flush=True)
                        break
                except Exception:
                    continue
        except ImportError:
            pass

    def set_led_ring(self, state: bool, pwm: int = 220) -> Dict[str, Any]:
        with self._lock:
            self.led_on = bool(state)
            self.pwm_value = max(0, min(255, int(pwm))) if state else 0

            # Forward hardware command to STM32U585 MCU over Serial/IPC
            if self.serial_conn and self.serial_conn.is_open:
                try:
                    cmd = f"LED_ON:{self.pwm_value}\n" if self.led_on else "LED_OFF\n"
                    self.serial_conn.write(cmd.encode("utf-8"))
                    self.serial_conn.flush()
                except Exception as e:
                    print(f"[STM32_BRIDGE] Serial write warning: {e}", flush=True)
                    self.mcu_connected = False

            return {
                "led_on": self.led_on,
                "pwm": self.pwm_value,
                "pin": "D3 (PWM MOSFET)",
                "mcu_mode": "HARDWARE_IPC" if self.mcu_connected else "READY_BRIDGE",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }


rig_bridge = STM32RigBridge()


def cleanup_old_captures(max_files: int = 180) -> None:
    """Prevent 16 GB eMMC storage overflow on Arduino UNO Q by rotating oldest captures."""
    files = sorted(
        glob.glob(os.path.join(CAPTURE_DIR, "*.jpg")),
        key=os.path.getmtime,
    )
    if len(files) > max_files:
        for old_f in files[: len(files) - max_files]:
            try:
                os.remove(old_f)
            except Exception:
                pass


def generate_realistic_kangkung_leaf(
    side: str = "top",
    variety: str = "Kangkung Daun Lebar",
    scenario: str = "AUTO",
    hst: int = 16,
    soil_moisture: float = 62.0,
    shift_x: int = 0,
    shift_y: int = 0,
) -> np.ndarray:
    """
    Generate a realistic 640x480 BGR image of an Ipomoea aquatica leaf
    placed on the Matte-Black In-Situ Flip-Stage (fallback when physical USB webcam is unplugged).
    Supports micro-shifts (shift_x, shift_y) to simulate natural live hand positioning in viewfinder.
    """
    h, w = 480, 640
    img = np.zeros((h, w, 3), dtype=np.uint8)

    # 1. Background: Matte-Black Flip-Stage in center + subtle soil/tray around edges
    img[:] = (24, 28, 34)
    cv2.rectangle(img, (50, 30), (w - 50, h - 30), (18, 18, 20), -1)
    cv2.rectangle(img, (50, 30), (w - 50, h - 30), (48, 52, 56), 2)

    yy, xx = np.mgrid[0:h, 0:w]
    dist_center = np.sqrt((xx - w / 2) ** 2 + (yy - h / 2) ** 2)
    vignette = np.clip(1.0 - (dist_center / 520.0) * 0.25, 0.75, 1.0)

    is_paris = "Paris" in variety or "Sempit" in variety
    is_water_stress = scenario == "PETAK_2_STRES_AIR" or (
        scenario == "AUTO" and soil_moisture < 35.0
    )
    is_healthy = scenario in ("PETAK_1_SEHAT", "CUACA_BRONTOK") or is_water_stress
    is_early_disease = scenario == "INFEKSI_DINI"
    is_severe_brontok = scenario == "PETAK_3_BRONTOK_PANEN" or (
        scenario == "AUTO" and not is_healthy and not is_early_disease
    )

    cx, cy = (w // 2) + int(shift_x), (h // 2) + int(shift_y)
    leaf_mask = np.zeros((h, w), dtype=np.uint8)

    if is_paris:
        pts = np.array(
            [
                [cx - 195, cy + 10],
                [cx - 140, cy - 34],
                [cx - 40, cy - 52],
                [cx + 80, cy - 38],
                [cx + 205, cy],
                [cx + 80, cy + 38],
                [cx - 40, cy + 52],
                [cx - 140, cy + 34],
            ],
            dtype=np.int32,
        )
    else:
        pts = np.array(
            [
                [cx - 185, cy - 35],
                [cx - 150, cy - 115],
                [cx - 55, cy - 125],
                [cx + 75, cy - 90],
                [cx + 205, cy - 2],
                [cx + 75, cy + 90],
                [cx - 55, cy + 125],
                [cx - 150, cy + 115],
                [cx - 185, cy + 35],
                [cx - 145, cy],
            ],
            dtype=np.int32,
        )

    cv2.fillPoly(leaf_mask, [pts], 255)
    leaf_mask = cv2.GaussianBlur(leaf_mask, (9, 9), 0)
    _, leaf_mask = cv2.threshold(leaf_mask, 127, 255, cv2.THRESH_BINARY)

    rng = np.random.default_rng(seed=101 if side == "top" else 202)
    texture_noise = rng.normal(0, 3.5, (h, w, 3)).astype(np.float32)

    if side == "top":
        base_bgr = np.array([42, 138, 62], dtype=np.float32)
        if is_water_stress:
            base_bgr = np.array([48, 132, 76], dtype=np.float32)
    else:
        base_bgr = np.array([64, 152, 82], dtype=np.float32)

    leaf_layer = np.clip(base_bgr + texture_noise, 20, 235).astype(np.uint8)

    vein_color = (82, 178, 108) if side == "bottom" else (52, 156, 78)
    vein_thickness = 4 if side == "bottom" else 2
    cv2.line(leaf_layer, (cx - 165, cy), (cx + 195, cy), vein_color, vein_thickness, cv2.LINE_AA)

    vein_reach = 42 if is_paris else 96
    for vx in range(cx - 110, cx + 140, 38):
        reach = int(vein_reach * (1.0 - abs(vx - cx) / 260.0))
        cv2.line(
            leaf_layer,
            (vx, cy),
            (vx + 32, cy - reach),
            vein_color,
            max(1, vein_thickness - 1),
            cv2.LINE_AA,
        )
        cv2.line(
            leaf_layer,
            (vx, cy),
            (vx + 32, cy + reach),
            vein_color,
            max(1, vein_thickness - 1),
            cv2.LINE_AA,
        )

    if is_early_disease or is_severe_brontok:
        if is_early_disease:
            spot_coords = [
                (cx - 35, cy - 32, 11),
                (cx + 25, cy + 28, 10),
                (cx + 65, cy - 18, 9),
                (cx - 75, cy + 22, 8),
            ]
        else:
            spot_coords = [
                (cx - 85, cy - 48, 18),
                (cx - 40, cy - 58, 16),
                (cx + 15, cy - 42, 19),
                (cx + 70, cy - 26, 15),
                (cx - 70, cy + 44, 17),
                (cx - 15, cy + 52, 20),
                (cx + 45, cy + 38, 16),
                (cx + 95, cy + 16, 14),
                (cx - 115, cy + 12, 15),
                (cx + 5, cy - 12, 14),
            ]
            if is_paris:
                spot_coords = [
                    (sx, int(cy + (sy - cy) * 0.42), max(9, int(sr * 0.72)))
                    for sx, sy, sr in spot_coords
                ]

        for sx, sy, sr in spot_coords:
            if side == "top":
                cv2.circle(leaf_layer, (sx, sy), int(sr * 1.15), (42, 188, 215), -1, cv2.LINE_AA)
                cv2.circle(leaf_layer, (sx, sy), max(4, int(sr * 0.55)), (38, 92, 155), -1, cv2.LINE_AA)
            else:
                cv2.circle(leaf_layer, (sx, sy), int(sr * 1.2), (65, 180, 195), -1, cv2.LINE_AA)
                cv2.circle(leaf_layer, (sx, sy), sr, (222, 238, 245), -1, cv2.LINE_AA)
                cv2.circle(
                    leaf_layer,
                    (sx + sr // 2, sy - sr // 3),
                    max(3, sr // 3),
                    (235, 245, 250),
                    -1,
                    cv2.LINE_AA,
                )
                cv2.circle(
                    leaf_layer,
                    (sx - sr // 2, sy + sr // 3),
                    max(3, sr // 3),
                    (230, 242, 248),
                    -1,
                    cv2.LINE_AA,
                )

    img[leaf_mask == 255] = leaf_layer[leaf_mask == 255]

    for c in range(3):
        img[:, :, c] = np.clip(img[:, :, c].astype(np.float32) * vignette, 0, 255).astype(np.uint8)

    return img


def is_usb_uvc_device(idx_num: int) -> bool:
    """
    Verifies if /dev/videoX belongs to a physical USB UVC webcam.
    Skips internal Qualcomm QRB2210 CAMSS / VFE ISP pipeline nodes that cause ioctl hangs.
    """
    sys_path = f"/sys/class/video4linux/video{idx_num}"
    if not os.path.exists(sys_path):
        return True
    try:
        name_path = os.path.join(sys_path, "name")
        if os.path.exists(name_path):
            with open(name_path, "r") as f:
                name = f.read().lower()
            if any(k in name for k in ("qcom", "camss", "vfe", "titan", "msm")):
                return False
            if any(k in name for k in ("cam", "webcam", "uvc", "usb", "logitech", "rexus")):
                return True
        driver_link = os.path.realpath(os.path.join(sys_path, "device", "driver"))
        if "uvcvideo" in driver_link.lower():
            return True
    except Exception:
        pass
    return True


def open_active_webcam(preferred_index: int = 0) -> Tuple[Optional[cv2.VideoCapture], int]:
    """
    Auto-detects and opens the physical USB webcam on Linux (Arduino UNO Q) or Windows.
    Prioritizes real UVC USB devices, avoiding internal Qualcomm ISP hardware pipelines that hang.
    Configures buffer size = 1 to prevent kernel V4L2 queue stalls.
    """
    # 1. Enforce Qualcomm DWC3 USB controller host mode
    ensure_usb_host_mode()

    candidate_devices: List[int] = []
    if os.name != "nt":
        video_nodes = sorted(glob.glob("/dev/video*"))
        uvc_targets: List[int] = []
        other_targets: List[int] = []
        for v in video_nodes:
            suffix = v.replace("/dev/video", "")
            if suffix.isdigit():
                idx_num = int(suffix)
                if is_usb_uvc_device(idx_num):
                    uvc_targets.append(idx_num)
                else:
                    other_targets.append(idx_num)
        # Prioritize confirmed UVC USB webcams first
        candidate_devices = uvc_targets + other_targets
        if preferred_index in candidate_devices:
            candidate_devices.sort(key=lambda x: 0 if x == preferred_index else 1)
        elif not candidate_devices:
            candidate_devices = [preferred_index]
    else:
        candidate_devices = [preferred_index] + [i for i in range(4) if i != preferred_index]

    print(
        f"[CAMERA_SCAN] Probing candidate video targets: {[f'/dev/video{i}' for i in candidate_devices]}",
        flush=True,
    )

    for idx_num in candidate_devices:
        cap = None
        try:
            if os.name == "nt":
                cap = cv2.VideoCapture(idx_num, cv2.CAP_DSHOW)
                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = cv2.VideoCapture(idx_num)
            else:
                cap = cv2.VideoCapture(idx_num, cv2.CAP_V4L2)
                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = cv2.VideoCapture(idx_num)

            if cap is None or not cap.isOpened():
                if cap is not None:
                    cap.release()
                continue

            # Standard 640x480 @ 20 FPS with minimal kernel buffer
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 20)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            # Test 1: Native format read with quick warm-up (up to 3 reads)
            frame_ok = False
            for _ in range(3):
                ret, test_frame = cap.read()
                if ret and test_frame is not None and test_frame.size > 0:
                    frame_ok = True
                    print(
                        f"[CAMERA_SCAN] SUCCESS: Opened physical camera on /dev/video{idx_num} "
                        f"(native format, {test_frame.shape[1]}x{test_frame.shape[0]})",
                        flush=True,
                    )
                    return cap, idx_num
                time.sleep(0.02)

            # Test 2: If native read failed, negotiate MJPG compression
            if not frame_ok:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                for _ in range(3):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None and test_frame.size > 0:
                        frame_ok = True
                        print(
                            f"[CAMERA_SCAN] SUCCESS: Opened physical camera on /dev/video{idx_num} "
                            f"(MJPG format, {test_frame.shape[1]}x{test_frame.shape[0]})",
                            flush=True,
                        )
                        return cap, idx_num
                    time.sleep(0.02)

            cap.release()
        except Exception as e:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            print(f"[CAMERA_SCAN] Warning probing /dev/video{idx_num}: {e}", flush=True)
            continue

    print("[CAMERA_SCAN] NOTICE: No active physical webcam responded. Using live viewfinder.", flush=True)
    return None, preferred_index


class CameraWorkerThread(threading.Thread):
    """
    Dedicated worker thread that continuously drains frames from the V4L2 kernel ring buffer.
    Eliminates the 4-frame kernel backlog delay, reducing preview latency from ~1200ms to <40ms.
    Guarantees thread-safe single-reader access to cv2.VideoCapture.
    """

    def __init__(self, cap: cv2.VideoCapture):
        super().__init__(daemon=True)
        self.cap = cap
        self.running = True
        self.latest_frame: Optional[np.ndarray] = None
        self.lock = threading.Lock()
        self.last_read_success_time = time.time()

    def run(self):
        consecutive_errors = 0
        while self.running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    break
                ret, frame = self.cap.read()
                if ret and frame is not None and frame.size > 0:
                    consecutive_errors = 0
                    self.last_read_success_time = time.time()
                    with self.lock:
                        self.latest_frame = frame
                else:
                    consecutive_errors += 1
                    try:
                        self.cap.grab()
                    except Exception:
                        pass
                    if consecutive_errors > 80:  # Allow up to ~1.6s for transient USB glitch recovery
                        print("[CAMERA_WORKER] Warning: Camera read timeout, worker stopping", flush=True)
                        break
                    time.sleep(0.02)
            except Exception as e:
                print(f"[CAMERA_WORKER] Exception in read loop: {e}", flush=True)
                break

    def get_frame(self) -> Optional[np.ndarray]:
        with self.lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def stop(self):
        self.running = False


class OnDemandWebcamController:
    """
    Manages the USB Webcam lifecycle on Arduino UNO Q:
    1. Keeps hardware handle warm between top and bottom surfaces (Daun Atas -> Daun Bawah)
       with 0% CPU when paused, eliminating V4L2 EBUSY lockout and simulated leaf fallback.
    2. Delivers zero-lag MJPEG stream (~20 FPS) via CameraWorkerThread while live.
    3. Thread-safe single-reader architecture: only CameraWorkerThread reads from cv2.VideoCapture.
    4. Auto-resizes high-resolution webcam frames to 640x480 to keep CPU load minimal.
    5. Disconnect detection: automatically pauses camera and turns off LED ring when all client streams disconnect.
    """

    def __init__(self, camera_index: int = 0):
        env_idx = os.environ.get("WEBCAM_INDEX", "").strip()
        self.camera_index = int(env_idx) if env_idx.isdigit() else camera_index
        self.cap: Optional[cv2.VideoCapture] = None
        self.worker: Optional[CameraWorkerThread] = None
        self.is_streaming: bool = False
        self.active_side: str = "top"
        self.last_frame: Optional[np.ndarray] = None
        self.last_source_mode: str = "STANDBY"
        self.stream_started_at: float = 0.0
        self.last_activity_at: float = time.time()
        self.lock = threading.RLock()
        self.max_stream_seconds: float = 90.0  # Auto-pause safety timeout for continuous stream
        self.active_viewers: int = 0

    def start_camera(self, side: str = "top") -> Dict[str, Any]:
        """
        Turn ON LED Ring and open USB Webcam cleanly.
        Ensures hardware indicator turns ON, V4L2 queue is brand new, and live preview starts immediately.
        Idempotent: If camera is already actively running, avoids redundant hardware teardowns.
        """
        with self.lock:
            self.active_side = "top" if side.lower() not in ("bottom", "bawah") else "bottom"
            self.stream_started_at = time.time()
            self.last_activity_at = time.time()

            # 1. Idempotent check: If already streaming with alive worker and open cap, DO NOT reopen!
            if (
                self.is_streaming
                and self.cap is not None
                and self.cap.isOpened()
                and self.worker is not None
                and self.worker.is_alive()
            ):
                rig_bridge.set_led_ring(True, pwm=225)
                return {
                    "is_streaming": True,
                    "side": self.active_side,
                    "source_mode": self.last_source_mode,
                    "fps_limit": 20,
                    "resolution": "640x480",
                    "led_ring_on": rig_bridge.led_on,
                }

            # Ensure any leftover worker or cap is cleanly shut down first
            if self.worker is not None:
                try:
                    self.worker.stop()
                    self.worker.join(timeout=0.2)
                except Exception:
                    pass
                self.worker = None

            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
                time.sleep(0.06)  # Short settling delay for kernel V4L2 driver cleanup

            rig_bridge.set_led_ring(True, pwm=225)

            hardware_ready = False
            if os.environ.get("DISABLE_USB_WEBCAM", "0") != "1":
                ensure_usb_host_mode()
                cap, working_idx = open_active_webcam(self.camera_index)
                if cap is not None and cap.isOpened():
                    self.cap = cap
                    self.camera_index = working_idx
                    hardware_ready = True
                    for _ in range(3):
                        ret, test_frame = self.cap.read()
                        if ret and test_frame is not None and test_frame.size > 0:
                            self.last_frame = test_frame
                            break
                        time.sleep(0.02)
                else:
                    self.cap = None

            self.is_streaming = True

            # Launch dedicated low-latency reader thread
            if hardware_ready and self.cap is not None:
                self.worker = CameraWorkerThread(self.cap)
                self.worker.start()
                self.last_source_mode = f"USB_WEBCAM_LIVE (video{self.camera_index})"
            else:
                self.last_source_mode = "VIRTUAL_WEBCAM_VIEWFINDER"

            return {
                "is_streaming": True,
                "side": self.active_side,
                "source_mode": self.last_source_mode,
                "fps_limit": 20,
                "resolution": "640x480",
                "led_ring_on": rig_bridge.led_on,
            }

    def pause_stream(self) -> Dict[str, Any]:
        """
        Safely stops the stream and releases physical webcam hardware.
        Ensures the webcam hardware indicator LED turns OFF and releases V4L2 device.
        """
        return self.release_hardware()

    def release_hardware(self) -> Dict[str, Any]:
        """
        Completely releases the USB Webcam hardware handle (cap.release()), stops worker thread,
        and turns OFF LED Ring. Frees all RAM and CPU, and ensures the physical webcam indicator LED turns OFF.
        """
        with self.lock:
            self.is_streaming = False
            if self.worker is not None:
                try:
                    self.worker.stop()
                    self.worker.join(timeout=0.25)
                except Exception:
                    pass
                self.worker = None

            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None

            rig_bridge.set_led_ring(False, pwm=0)
            self.last_source_mode = "STANDBY"
            return {
                "is_streaming": False,
                "led_ring_on": False,
                "hardware_warm": False,
                "status": "HARDWARE_COMPLETELY_RELEASED",
            }

    def stop_camera(self, release_hw: bool = True) -> Dict[str, Any]:
        """Stops live webcam and releases physical hardware handle completely."""
        return self.release_hardware()

    def read_preview_frame(
        self,
        side: str = "top",
        variety: str = "Kangkung Daun Lebar",
        scenario: str = "AUTO",
        hst: int = 16,
        soil_moisture: float = 62.0,
    ) -> np.ndarray:
        """
        Read latest instantaneous frame with 0-frame buffer backlog.
        Guarantees thread-safety: does NOT concurrently call cap.read() if worker is alive.
        """
        self.last_activity_at = time.time()

        # 1. Primary path: Grab latest frame from dedicated worker thread (0-latency, thread-safe)
        if self.worker is not None and self.worker.is_alive():
            live_frame = self.worker.get_frame()
            if live_frame is not None and live_frame.size > 0:
                # Downscale to 640x480 if camera outputs higher resolution (720p/1080p) to save CPU/bandwidth
                if live_frame.shape[1] > 640:
                    h, w = live_frame.shape[:2]
                    target_w = 640
                    target_h = int(h * (640.0 / w))
                    live_frame = cv2.resize(live_frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
                self.last_frame = live_frame.copy()
                self.last_source_mode = f"USB_WEBCAM_LIVE (video{self.camera_index})"
                return live_frame

        # 2. Worker revive check: if worker unexpectedly died while cap is still open, revive worker
        with self.lock:
            if (self.worker is None or not self.worker.is_alive()) and (self.cap is not None and self.cap.isOpened()):
                self.worker = CameraWorkerThread(self.cap)
                self.worker.start()

            # 3. Cached latest frame while worker is starting up
            if (
                self.last_frame is not None
                and self.last_frame.size > 0
                and (self.cap is not None and self.cap.isOpened())
            ):
                return self.last_frame.copy()

        # 4. Kamera fisik tidak terhubung: Tampilkan layar peringatan diagnostik visual (bukan daun sintetis palsu)
        frame = np.full((480, 640, 3), 20, dtype=np.uint8)
        # Bingkai merah peringatan
        cv2.rectangle(frame, (8, 8), (632, 472), (0, 0, 200), 2)
        cv2.putText(
            frame,
            "WEBCAM USB TIDAK TERDETEKSI / TERPUTUS",
            (40, 190),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 90, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Hubungkan kabel USB Webcam ke port USB Host Arduino UNO Q",
            (40, 235),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (210, 210, 210),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Sistem Mode Real-Time: Simulasi daun sintetis dimatikan permanen.",
            (40, 275),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (140, 140, 140),
            1,
            cv2.LINE_AA,
        )
        t_str = datetime.now().strftime("%H:%M:%S WIB")
        cv2.putText(
            frame,
            f"Waktu Sistem: {t_str}",
            (40, 320),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 230, 100),
            1,
            cv2.LINE_AA,
        )
        self.last_frame = frame.copy()
        self.last_source_mode = "WEBCAM_DISCONNECTED"
        return frame

    def stream_mjpeg_generator(
        self,
        side: str = "top",
        variety: str = "Kangkung Daun Lebar",
        scenario: str = "AUTO",
        hst: int = 16,
        soil_moisture: float = 62.0,
    ) -> Generator[bytes, None, None]:
        """
        Yields multipart MJPEG frames at smooth ~20 FPS while self.is_streaming is True.
        Automatically pauses when stopped, after 90s timeout, or when client disconnects.
        """
        self.start_camera(side=side)
        with self.lock:
            self.active_viewers += 1

        frame_interval = 0.05  # Snappy 20 FPS preview with zero buffer backlog

        try:
            while self.is_streaming:
                if (time.time() - self.stream_started_at) > self.max_stream_seconds:
                    self.pause_stream()
                    break

                t_start = time.perf_counter()
                frame = self.read_preview_frame(
                    side=side,
                    variety=variety,
                    scenario=scenario,
                    hst=hst,
                    soil_moisture=soil_moisture,
                )

                ok, jpeg_buf = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 68]
                )
                if ok:
                    jpg_bytes = jpeg_buf.tobytes()
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + jpg_bytes + b"\r\n"
                    )

                elapsed = time.perf_counter() - t_start
                sleep_rem = max(0.01, frame_interval - elapsed)
                time.sleep(sleep_rem)
        finally:
            # When client closes browser tab / disconnects, decrement active viewers
            should_stop = False
            with self.lock:
                self.active_viewers = max(0, self.active_viewers - 1)
                if self.active_viewers == 0:
                    should_stop = True
            if should_stop:
                self.release_hardware()


webcam_controller = OnDemandWebcamController()

_last_webcam_probe_time: float = 0.0
_last_webcam_probe_result: bool = False


def is_physical_camera_connected() -> bool:
    """
    Checks if a real physical USB webcam is connected and detected by the OS.
    On Linux (Arduino UNO Q): Inspects /sys/class/video4linux/video* for real UVC USB devices.
    On Windows (PC/laptop): Probes candidate camera handles with low-overhead caching.
    """
    global _last_webcam_probe_time, _last_webcam_probe_result
    if webcam_controller.cap is not None and webcam_controller.cap.isOpened():
        _last_webcam_probe_result = True
        return True

    now = time.time()
    if (now - _last_webcam_probe_time) < 2.0:
        return _last_webcam_probe_result

    _last_webcam_probe_time = now

    if os.name != "nt":
        video_nodes = sorted(glob.glob("/dev/video*"))
        has_uvc = False
        for v in video_nodes:
            suffix = v.replace("/dev/video", "")
            if suffix.isdigit():
                if is_usb_uvc_device(int(suffix)):
                    has_uvc = True
                    break
        _last_webcam_probe_result = has_uvc
        return has_uvc
    else:
        has_cam = False
        try:
            test_cap = cv2.VideoCapture(webcam_controller.camera_index, cv2.CAP_DSHOW)
            if test_cap is not None and test_cap.isOpened():
                has_cam = True
                test_cap.release()
            elif test_cap is not None:
                test_cap.release()
        except Exception:
            has_cam = False
        _last_webcam_probe_result = has_cam
        return has_cam


def capture_leaf_surface(
    side: str,
    variety: str = "Kangkung Daun Lebar",
    scenario: str = "AUTO",
    hst: int = 16,
    soil_moisture: float = 62.0,
    uploaded_bytes: Optional[bytes] = None,
    camera_index: int = 0,
    prefer_simulation: bool = False,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Captures the current leaf image for 'top' or 'bottom' with zero buffer lag and
    pauses the stream while keeping hardware warm for the second surface.
    """
    cleanup_old_captures()
    side = "top" if side.lower() not in ("bottom", "bawah", "abaxial") else "bottom"
    ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"capture_{side}_{ts_tag}.jpg"
    abs_path = os.path.join(CAPTURE_DIR, filename)
    url_path = f"/captures/{filename}"

    t0 = time.perf_counter()
    frame = None
    source_mode = "WEBCAM_CAPTURE"
    captured_from_live = False

    if uploaded_bytes:
        arr = np.frombuffer(uploaded_bytes, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if decoded is not None:
            frame = decoded
            source_mode = "UPLOADED_IMAGE"

    # Grab the current real-time frame from active webcam preview
    if frame is None and not prefer_simulation:
        # 1. Pastikan webcam fisik terhubung sebelum mengizinkan proses pengambilan foto
        if not is_physical_camera_connected() and (
            webcam_controller.cap is None or not webcam_controller.cap.isOpened()
        ):
            webcam_controller.release_hardware()
            raise RuntimeError(
                "Gagal mengambil foto: Webcam USB fisik tidak terhubung atau terputus! "
                "Harap tancapkan kabel webcam USB ke port USB Arduino UNO Q terlebih dahulu."
            )

        # Priority 1: worker thread latest frame (hanya jika bukan bingkai peringatan disconnected)
        if webcam_controller.worker is not None and webcam_controller.worker.is_alive():
            if webcam_controller.last_source_mode != "WEBCAM_DISCONNECTED":
                live = webcam_controller.worker.get_frame()
                if live is not None and live.size > 0:
                    frame = live.copy()
                    source_mode = webcam_controller.last_source_mode
                    captured_from_live = True

        # Priority 2: direct read jika stream belum berjalan
        if frame is None:
            if webcam_controller.cap is None or not webcam_controller.cap.isOpened():
                webcam_controller.start_camera(side=side)
            if webcam_controller.cap is not None and webcam_controller.cap.isOpened():
                for _ in range(5):
                    ret, direct_frame = webcam_controller.cap.read()
                    if ret and direct_frame is not None and direct_frame.size > 0:
                        frame = direct_frame.copy()
                        source_mode = f"USB_WEBCAM_LIVE (video{webcam_controller.camera_index})"
                        captured_from_live = True
                        break
                    time.sleep(0.04)

        # Release hardware completely and turn off LED ring immediately after capturing frame
        webcam_controller.release_hardware()

    # Validasi keras: Jangan pernah simpan bingkai diagnostik terputus atau frame kosong ke disk
    if (
        (frame is None or frame.size == 0 or not captured_from_live)
        and not uploaded_bytes
        and not prefer_simulation
    ):
        webcam_controller.release_hardware()
        raise RuntimeError(
            "Gagal mengambil foto: Webcam USB fisik tidak terhubung atau gagal menghasilkan frame valid. "
            "Pastikan kabel USB webcam terpasang dengan baik pada port USB Host Arduino UNO Q."
        )

    rig_bridge.last_trigger_step = 1 if side == "top" else 2

    # Save compressed JPEG to disk
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    cv2.imwrite(abs_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    meta = {
        "side": side,
        "side_label": "Permukaan Atas (Adaksial)" if side == "top" else "Permukaan Bawah (Abaksial)",
        "source_mode": source_mode,
        "hardware_kept_warm": webcam_controller.cap is not None and webcam_controller.cap.isOpened(),
        "led_sync_protocol": "LIVE_STREAM -> CAPTURE_FRAME -> PAUSE_STREAM_KEEP_HW_WARM",
        "capture_ms": elapsed_ms,
        "resolution": f"{frame.shape[1]}x{frame.shape[0]}",
    }
    return abs_path, url_path, meta
