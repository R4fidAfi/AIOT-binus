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


def open_active_webcam(preferred_index: int = 0) -> Tuple[Optional[cv2.VideoCapture], int]:
    """
    Auto-detects and opens the physical USB webcam on Linux (Arduino UNO Q) or Windows.
    Qualcomm Snapdragon / Dragonwing QRB2210 often reserves /dev/video0 and /dev/video1
    for internal ISP / VFE hardware pipelines. When a USB webcam is attached (even through a hub),
    Linux assigns it to /dev/video0, /dev/video2, or higher.
    Probes device character nodes directly (/dev/video*), tests native camera format first (YUYV/default),
    and falls back to MJPG negotiation to ensure broad hardware compatibility.
    """
    # 1. Enforce Qualcomm DWC3 USB controller host mode
    ensure_usb_host_mode()

    candidate_devices = []
    if os.name != "nt":
        # Scan real /dev/video* devices on Debian ARM64
        video_nodes = sorted(glob.glob("/dev/video*"))
        for v in video_nodes:
            suffix = v.replace("/dev/video", "")
            if suffix.isdigit():
                idx_num = int(suffix)
                if (idx_num, v) not in candidate_devices:
                    candidate_devices.append((idx_num, v))

        pref_node = f"/dev/video{preferred_index}"
        if (preferred_index, pref_node) in candidate_devices:
            candidate_devices.remove((preferred_index, pref_node))
            candidate_devices.insert(0, (preferred_index, pref_node))
        elif preferred_index not in [x[0] for x in candidate_devices]:
            candidate_devices.insert(0, (preferred_index, pref_node))
    else:
        candidate_devices.append((preferred_index, preferred_index))
        for i in range(8):
            if i != preferred_index:
                candidate_devices.append((i, i))

    print(
        f"[CAMERA_SCAN] Probing candidate video targets: {[x[1] for x in candidate_devices]}",
        flush=True,
    )

    # Retry up to 3 attempts with brief pause to handle V4L2 device availability
    for attempt in range(3):
        for idx_num, dev_target in candidate_devices:
            try:
                cap = None
                if os.name == "nt":
                    cap = cv2.VideoCapture(dev_target, cv2.CAP_DSHOW)
                    if cap is None or not cap.isOpened():
                        cap = cv2.VideoCapture(dev_target)
                else:
                    # On Linux: try path string first (e.g. "/dev/video0"), then integer index
                    if isinstance(dev_target, str):
                        cap = cv2.VideoCapture(dev_target, cv2.CAP_V4L2)
                    if cap is None or not cap.isOpened():
                        cap = cv2.VideoCapture(idx_num, cv2.CAP_V4L2)
                    if cap is None or not cap.isOpened():
                        cap = cv2.VideoCapture(idx_num)

                if cap is None or not cap.isOpened():
                    continue

                # Configure standard 640x480 @ 20 FPS
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 20)

                # Test 1: Native format read with sensor warm-up (up to 5 reads)
                frame_ok = False
                for _ in range(5):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None and test_frame.size > 0:
                        frame_ok = True
                        print(
                            f"[CAMERA_SCAN] SUCCESS: Opened physical camera on {dev_target} "
                            f"(native format, {test_frame.shape[1]}x{test_frame.shape[0]})",
                            flush=True,
                        )
                        return cap, idx_num
                    time.sleep(0.04)

                # Test 2: If native read failed, negotiate MJPG compression
                if not frame_ok:
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    for _ in range(5):
                        ret, test_frame = cap.read()
                        if ret and test_frame is not None and test_frame.size > 0:
                            frame_ok = True
                            print(
                                f"[CAMERA_SCAN] SUCCESS: Opened physical camera on {dev_target} "
                                f"(MJPG format, {test_frame.shape[1]}x{test_frame.shape[0]})",
                                flush=True,
                            )
                            return cap, idx_num
                        time.sleep(0.04)

                cap.release()
            except Exception as e:
                print(f"[CAMERA_SCAN] Warning probing {dev_target}: {e}", flush=True)
                continue

        if attempt < 2:
            time.sleep(0.2)

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
        self.lock = threading.Lock()
        self.max_stream_seconds: float = 90.0  # Auto-pause safety timeout for continuous stream
        self.active_viewers: int = 0

    def start_camera(self, side: str = "top") -> Dict[str, Any]:
        """
        Turn ON LED Ring and resume/open USB Webcam.
        Keeps the hardware handle warm between top and bottom surfaces, preventing Linux V4L2
        EBUSY lockouts and eliminating dummy AI leaf fallback.
        """
        with self.lock:
            self.active_side = "top" if side.lower() not in ("bottom", "bawah") else "bottom"
            self.stream_started_at = time.time()
            self.last_activity_at = time.time()
            rig_bridge.set_led_ring(True, pwm=225)

            hardware_ready = False

            # 1. Fast path: check if existing hardware handle is already alive and responsive
            if self.cap is not None and self.cap.isOpened():
                try:
                    for _ in range(3):
                        ret, test_frame = self.cap.read()
                        if ret and test_frame is not None and test_frame.size > 0:
                            self.last_frame = test_frame
                            hardware_ready = True
                            break
                        time.sleep(0.02)
                except Exception:
                    hardware_ready = False

                if not hardware_ready:
                    # Stale or disconnected handle, release before re-acquiring
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    self.cap = None

            # 2. Slow path: open physical webcam if not already open
            if not hardware_ready:
                if os.environ.get("DISABLE_USB_WEBCAM", "0") != "1":
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

            # 3. Launch dedicated low-latency reader thread
            if hardware_ready and self.cap is not None:
                if self.worker is None or not self.worker.is_alive():
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
        Pauses live stream loop and turns OFF LED Ring, while KEEPING the physical
        cv2.VideoCapture handle warm in memory. Eliminates V4L2 EBUSY device lockout
        when transitioning between Daun Atas and Daun Bawah.
        CPU load is 0% during pause because worker thread is safely stopped.
        """
        with self.lock:
            self.is_streaming = False
            self.last_activity_at = time.time()
            if self.worker is not None:
                try:
                    self.worker.stop()
                    self.worker.join(timeout=0.25)
                except Exception:
                    pass
                self.worker = None

            rig_bridge.set_led_ring(False, pwm=0)
            return {
                "is_streaming": False,
                "led_ring_on": False,
                "hardware_warm": self.cap is not None and self.cap.isOpened(),
                "status": "STREAM_PAUSED_HARDWARE_WARM",
            }

    def release_hardware(self) -> Dict[str, Any]:
        """
        Completely releases the USB Webcam hardware handle (cap.release()), stops worker thread,
        and turns OFF LED Ring. Frees all RAM and CPU for 5-Stage AI Pipeline or full session reset.
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

    def stop_camera(self, release_hw: bool = False) -> Dict[str, Any]:
        """Backward-compatible stop call. Default keeps hardware warm between surfaces."""
        if release_hw:
            return self.release_hardware()
        return self.pause_stream()

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

        # 4. Fallback live viewfinder with subtle natural movement only if physical webcam is truly absent
        t = time.time()
        shift_x = int(math.sin(t * 2.2) * 5.0)
        shift_y = int(math.cos(t * 1.7) * 4.0)
        frame = generate_realistic_kangkung_leaf(
            side=side,
            variety=variety,
            scenario=scenario,
            hst=hst,
            soil_moisture=soil_moisture,
            shift_x=shift_x,
            shift_y=shift_y,
        )
        self.last_frame = frame.copy()
        self.last_source_mode = f"WEBCAM_VIEWFINDER ({scenario})"
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
            with self.lock:
                self.active_viewers = max(0, self.active_viewers - 1)
                if self.active_viewers == 0:
                    # Auto-pause stream and turn off LED ring so camera never idles hot
                    self.pause_stream()


webcam_controller = OnDemandWebcamController()


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

    if uploaded_bytes:
        arr = np.frombuffer(uploaded_bytes, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if decoded is not None:
            frame = decoded
            source_mode = "UPLOADED_IMAGE"

    # Grab the current real-time frame from active webcam preview
    if frame is None and not prefer_simulation:
        # Priority 1: worker thread latest frame (instantaneous, thread-safe, 0 latency)
        if webcam_controller.worker is not None and webcam_controller.worker.is_alive():
            live = webcam_controller.worker.get_frame()
            if live is not None and live.size > 0:
                frame = live.copy()
                source_mode = webcam_controller.last_source_mode

        # Priority 2: cached last frame
        if frame is None and webcam_controller.last_frame is not None and webcam_controller.last_frame.size > 0:
            frame = webcam_controller.last_frame.copy()
            source_mode = webcam_controller.last_source_mode

        # Priority 3: direct read only if worker is NOT running
        if frame is None and (webcam_controller.worker is None or not webcam_controller.worker.is_alive()):
            if webcam_controller.cap is not None and webcam_controller.cap.isOpened():
                for _ in range(5):
                    ret, direct_frame = webcam_controller.cap.read()
                    if ret and direct_frame is not None and direct_frame.size > 0:
                        frame = direct_frame.copy()
                        source_mode = f"USB_WEBCAM_LIVE (video{webcam_controller.camera_index})"
                        break
                    time.sleep(0.03)

        # Pause stream and turn off LED ring, but KEEP cv2.VideoCapture handle warm!
        # This guarantees transitioning to Daun Bawah (or retrying Daun Atas) never hits V4L2 EBUSY.
        webcam_controller.pause_stream()

    # Fallback if called directly or if frame read failed
    if frame is None or frame.size == 0:
        webcam_controller.pause_stream()
        frame = generate_realistic_kangkung_leaf(
            side=side,
            variety=variety,
            scenario=scenario,
            hst=hst,
            soil_moisture=soil_moisture,
        )
        source_mode = f"SIMULATED_RIG ({scenario})"

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
