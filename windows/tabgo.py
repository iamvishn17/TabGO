import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QStackedWidget, QComboBox, QSlider,
    QGridLayout, QProgressBar, QButtonGroup, QRadioButton, QTextEdit,
    QSizePolicy
)

APP_NAME = "TabGO"
PORT = 38177
DARK = "#202225"
PANEL = "#282b2f"
PANEL2 = "#30343a"
TEXT = "#eef0f2"
MUTED = "#9299a3"
ACCENT = "#8b9cff"
GREEN = "#57d69a"
RED = "#ed7777"
AMBER = "#e8bd69"

def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

class WinMouse:
    """Mouse cursor bridge. Pressure is intentionally kept as telemetry until a signed pen HID driver exists."""
    def __init__(self):
        self.last = None
        self.user32 = ctypes.windll.user32 if sys.platform == "win32" else None

    def _send(self, flags, dx=0, dy=0):
        if not self.user32:
            return
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]
        item = INPUT()
        item.type = 0
        item.union.mi = MOUSEINPUT(dx, dy, 0, flags, 0, None)
        self.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))

    def move_absolute(self, nx, ny, screen):
        if not self.user32:
            return
        x0, y0, width, height = screen
        px = x0 + max(0.0, min(1.0, nx)) * max(1, width - 1)
        py = y0 + max(0.0, min(1.0, ny)) * max(1, height - 1)
        vx = self.user32.GetSystemMetrics(76)
        vy = self.user32.GetSystemMetrics(77)
        vw = max(1, self.user32.GetSystemMetrics(78))
        vh = max(1, self.user32.GetSystemMetrics(79))
        ax = int(max(0, min(65535, (px - vx) * 65535 / max(1, vw - 1))))
        ay = int(max(0, min(65535, (py - vy) * 65535 / max(1, vh - 1))))
        self._send(0x0001 | 0x8000 | 0x4000, ax, ay)
        self.last = (nx, ny)

    def move_relative(self, nx, ny, sensitivity=1800):
        if self.last is not None:
            dx = int((nx - self.last[0]) * sensitivity)
            dy = int((ny - self.last[1]) * sensitivity)
            if dx or dy:
                self._send(0x0001, dx, dy)
        self.last = (nx, ny)

    def button(self, down):
        self._send(0x0002 if down else 0x0004)

    def reset(self):
        self.last = None


class SyntheticPen:
    """Windows user-mode PT_PEN injection. No virtual HID or kernel driver installation."""
    def __init__(self):
        self.device = None
        self.user32 = None
        self.pointer_alive = False
        self.last = None
        self.last_error = 0
        if sys.platform != "win32":
            return
        try:
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            class POINTER_INFO(ctypes.Structure):
                _fields_ = [
                    ("pointerType", ctypes.c_int), ("pointerId", wintypes.DWORD),
                    ("frameId", wintypes.DWORD), ("pointerFlags", wintypes.DWORD),
                    ("sourceDevice", ctypes.c_void_p), ("hwndTarget", ctypes.c_void_p),
                    ("ptPixelLocation", POINT), ("ptHimetricLocation", POINT),
                    ("ptPixelLocationRaw", POINT), ("ptHimetricLocationRaw", POINT),
                    ("dwTime", wintypes.DWORD), ("historyCount", wintypes.DWORD),
                    ("InputData", ctypes.c_int), ("dwKeyStates", wintypes.DWORD),
                    ("PerformanceCount", ctypes.c_ulonglong), ("ButtonChangeType", ctypes.c_int)
                ]
            class POINTER_PEN_INFO(ctypes.Structure):
                _fields_ = [
                    ("pointerInfo", POINTER_INFO), ("penFlags", wintypes.DWORD),
                    ("penMask", wintypes.DWORD), ("pressure", wintypes.DWORD),
                    ("rotation", wintypes.DWORD), ("tiltX", ctypes.c_int), ("tiltY", ctypes.c_int)
                ]
            class PEN_UNION(ctypes.Union):
                _fields_ = [("penInfo", POINTER_PEN_INFO), ("pointerInfo", POINTER_INFO)]
            class POINTER_TYPE_INFO(ctypes.Structure):
                _anonymous_ = ("data",)
                _fields_ = [("type", wintypes.DWORD), ("data", PEN_UNION)]
            self.POINT = POINT
            self.POINTER_TYPE_INFO = POINTER_TYPE_INFO
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.CreateSyntheticPointerDevice.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
            self.user32.CreateSyntheticPointerDevice.restype = ctypes.c_void_p
            self.user32.InjectSyntheticPointerInput.argtypes = [ctypes.c_void_p, ctypes.POINTER(POINTER_TYPE_INFO), wintypes.UINT]
            self.user32.InjectSyntheticPointerInput.restype = wintypes.BOOL
            self.user32.DestroySyntheticPointerDevice.argtypes = [ctypes.c_void_p]
            self.user32.DestroySyntheticPointerDevice.restype = None
            self.device = self.user32.CreateSyntheticPointerDevice(3, 1, 3)
            if not self.device:
                self.last_error = ctypes.get_last_error()
        except Exception:
            self.device = None
            self.last_error = ctypes.get_last_error() if sys.platform == "win32" else 0

    @property
    def available(self):
        return bool(self.device)

    def send(self, nx, ny, pressure, action, screen, mode, sensitivity, tilt_x=0, tilt_y=0, tool="stylus"):
        if not self.device:
            return False
        try:
            vx = self.user32.GetSystemMetrics(76)
            vy = self.user32.GetSystemMetrics(77)
            vw = max(1, self.user32.GetSystemMetrics(78))
            vh = max(1, self.user32.GetSystemMetrics(79))
            if mode == "Relative":
                point = self.POINT()
                self.user32.GetCursorPos(ctypes.byref(point))
                if self.last is not None:
                    px = point.x + int((nx - self.last[0]) * sensitivity)
                    py = point.y + int((ny - self.last[1]) * sensitivity)
                else:
                    px, py = point.x, point.y
            else:
                x0, y0, width, height = screen
                px = int(x0 + max(0.0, min(1.0, nx)) * max(1, width - 1))
                py = int(y0 + max(0.0, min(1.0, ny)) * max(1, height - 1))
            self.last = (nx, ny)
            px = max(vx, min(vx + vw - 1, px))
            py = max(vy, min(vy + vh - 1, py))

            flags = 0x00002000
            if not self.pointer_alive and action != "hover_exit":
                flags |= 0x00000001
            if action == "hover_exit":
                flags |= 0x00020000
                self.pointer_alive = False
            elif action == "up":
                flags |= 0x00000002 | 0x00040000
                self.pointer_alive = True
            elif action == "down":
                flags |= 0x00000002 | 0x00000004 | 0x00010000 | 0x00000010
                self.pointer_alive = True
            elif action == "move" and pressure > 0:
                flags |= 0x00000002 | 0x00000004 | 0x00020000 | 0x00000010
                self.pointer_alive = True
            else:
                flags |= 0x00000002 | 0x00020000
                self.pointer_alive = True

            info = self.POINTER_TYPE_INFO()
            info.type = 3
            pen = info.penInfo
            pi = pen.pointerInfo
            pi.pointerType = 3
            pi.pointerId = 1
            pi.frameId = int(time.monotonic_ns() & 0xFFFFFFFF)
            pi.pointerFlags = flags
            pi.ptPixelLocation = self.POINT(px, py)
            pi.ptPixelLocationRaw = self.POINT(px, py)
            pi.historyCount = 1
            pen.penFlags = 0x0004 if tool == "eraser" else 0
            pen.penMask = 0x0001 | 0x0004 | 0x0008
            pen.pressure = int(max(0.0, min(1.0, pressure)) * 1024)
            pen.rotation = 0
            pen.tiltX = max(-90, min(90, int(tilt_x)))
            pen.tiltY = max(-90, min(90, int(tilt_y)))
            ok = self.user32.InjectSyntheticPointerInput(self.device, ctypes.byref(info), 1)
            if not ok:
                self.last_error = ctypes.get_last_error()
                return False
            return True
        except Exception:
            self.last_error = ctypes.get_last_error() if sys.platform == "win32" else 0
            return False

    def close(self):
        if self.device and self.user32:
            try:
                self.user32.DestroySyntheticPointerDevice(self.device)
            except Exception:
                pass
            self.device = None

class BridgeWorker(QThread):
    status = Signal(str, str)
    event_received = Signal(dict)
    log_line = Signal(str)

    def __init__(self):
        super().__init__()
        self.enabled = False
        self.running = True
        self.serial = ""
        self._lock = threading.Lock()

    def set_enabled(self, enabled, serial=""):
        with self._lock:
            self.enabled = enabled
            self.serial = serial

    def stop(self):
        self.running = False
        self.wait(1500)

    def _devices(self):
        adb = shutil.which("adb")
        if not adb:
            return None, []
        try:
            result = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=4)
            devices = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
            return adb, devices
        except Exception:
            return adb, []

    def run(self):
        last_status = ""
        while self.running:
            with self._lock:
                enabled, requested = self.enabled, self.serial
            if not enabled:
                if last_status != "Disconnected":
                    self.status.emit("Disconnected", "muted")
                    last_status = "Disconnected"
                time.sleep(0.25)
                continue
            adb, devices = self._devices()
            if not adb:
                message, color = "ADB not found — install Android Platform Tools", "bad"
                if message != last_status:
                    self.status.emit(message, color); last_status = message
                time.sleep(2); continue
            serial = requested if requested in devices else (devices[0] if devices else "")
            if not serial:
                message = "Connect tablet with USB debugging enabled"
                if message != last_status:
                    self.status.emit(message, "warn"); last_status = message
                time.sleep(1.2); continue
            try:
                subprocess.run([adb, "-s", serial, "forward", f"tcp:{PORT}", f"tcp:{PORT}"],
                               capture_output=True, text=True, timeout=5, check=True)
                sock = socket.create_connection(("127.0.0.1", PORT), timeout=2.5)
                sock.settimeout(0.7)
                self.status.emit(f"Connected · {serial}", "good")
                last_status = f"Connected · {serial}"
                self.log_line.emit(f"USB bridge connected to {serial}")
                buffer = b""
                with sock:
                    while self.running:
                        with self._lock:
                            still_enabled = self.enabled
                        if not still_enabled:
                            break
                        try:
                            chunk = sock.recv(8192)
                            if not chunk:
                                break
                            buffer += chunk
                            while b"\n" in buffer:
                                raw, buffer = buffer.split(b"\n", 1)
                                try:
                                    event = json.loads(raw.decode("utf-8"))
                                    self.event_received.emit(event)
                                except (ValueError, UnicodeDecodeError):
                                    self.log_line.emit("Ignored malformed pen packet")
                        except socket.timeout:
                            try:
                                sock.sendall(b"{}\n")
                            except OSError:
                                break
                self.log_line.emit("USB event connection closed")
            except (OSError, subprocess.SubprocessError) as exc:
                message = "Waiting for TabGO on the Android tablet"
                if message != last_status:
                    self.status.emit(message, "warn"); last_status = message
            time.sleep(0.7)
        self.status.emit("Disconnected", "muted")

class DotGrid(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.hover = None
        self.contact = False

    def set_pen(self, x, y, contact):
        self.hover = (x, y)
        self.contact = contact
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1b1d20"))
        p.setPen(QPen(QColor("#3a3e44"), 1))
        for x in range(12, self.width(), 22):
            for y in range(12, self.height(), 22):
                p.drawPoint(x, y)
        if self.hover:
            x = int(self.hover[0] * self.width())
            y = int(self.hover[1] * self.height())
            p.setPen(QPen(QColor(GREEN if self.contact else ACCENT), 2))
            p.drawEllipse(x - 8, y - 8, 16, 16)
            p.drawLine(x - 15, y, x + 15, y)
            p.drawLine(x, y - 15, x, y + 15)

class Card(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(10)
        label = QLabel(title.upper())
        label.setObjectName("eyebrow")
        self.layout.addWidget(label)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TabGO")
        self.resize(1120, 740)
        self.setMinimumSize(900, 620)
        self.mouse = WinMouse()
        self.synthetic_pen = SyntheticPen()
        self.mode = "Absolute"
        self.target_screen = 0
        self.pen_down = False
        self.last_event = {}
        self.worker = BridgeWorker()
        self.worker.status.connect(self.set_status)
        self.worker.event_received.connect(self.on_pen_event)
        self.worker.log_line.connect(self.add_log)
        self.worker.start()
        self._build_ui()
        self._load_screens()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_device_list)
        self.timer.start(3000)

    def _build_ui(self):
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(218)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 24, 18, 20)
        sl.setSpacing(8)
        brand = QLabel("TABGO")
        brand.setObjectName("brand")
        sl.addWidget(brand)
        sub = QLabel("GRAPHICS TABLET")
        sub.setObjectName("brandSub")
        sl.addWidget(sub)
        sl.addSpacing(28)
        self.nav_buttons = []
        self.stack = QStackedWidget()
        names = ["Dashboard", "Mapping", "Pen", "Diagnostics", "Settings"]
        for i, name in enumerate(names):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, idx=i: self.show_page(idx))
            self.nav_buttons.append(b)
            sl.addWidget(b)
        sl.addStretch(1)
        self.side_status = QLabel("●  DISCONNECTED")
        self.side_status.setObjectName("sideStatus")
        sl.addWidget(self.side_status)
        version = QLabel("TabGO Desktop  ·  Preview")
        version.setObjectName("muted")
        sl.addWidget(version)
        outer.addWidget(side)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(30, 24, 30, 24)
        cl.setSpacing(18)
        header = QHBoxLayout()
        self.page_title = QLabel("Dashboard")
        self.page_title.setObjectName("pageTitle")
        header.addWidget(self.page_title)
        header.addStretch(1)
        self.connection_badge = QLabel("●  DISCONNECTED")
        self.connection_badge.setObjectName("badgeMuted")
        header.addWidget(self.connection_badge)
        cl.addLayout(header)
        self._make_dashboard()
        self._make_mapping()
        self._make_pen()
        self._make_diagnostics()
        self._make_settings()
        cl.addWidget(self.stack, 1)
        outer.addWidget(content, 1)
        self.setCentralWidget(root)
        self.nav_buttons[0].setChecked(True)

    def _make_dashboard(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(16)
        row = QHBoxLayout()
        c1 = Card("Connection")
        self.connection_big = QLabel("Waiting for tablet")
        self.connection_big.setObjectName("metric")
        self.connection_detail = QLabel("Connect the tablet by USB and open TabGO on Android.")
        self.connection_detail.setObjectName("muted")
        c1.layout.addWidget(self.connection_big); c1.layout.addWidget(self.connection_detail)
        self.connect_button = QPushButton("Connect tablet")
        self.connect_button.setObjectName("primary")
        self.connect_button.clicked.connect(self.toggle_connection)
        c1.layout.addWidget(self.connect_button)
        c2 = Card("Live pressure")
        self.pressure_number = QLabel("0%")
        self.pressure_number.setObjectName("metric")
        self.pressure_bar = QProgressBar(); self.pressure_bar.setRange(0,100); self.pressure_bar.setValue(0); self.pressure_bar.setTextVisible(False)
        self.pressure_state = QLabel("No pen detected")
        self.pressure_state.setObjectName("muted")
        c2.layout.addWidget(self.pressure_number); c2.layout.addWidget(self.pressure_bar); c2.layout.addWidget(self.pressure_state)
        row.addWidget(c1, 3); row.addWidget(c2, 2); layout.addLayout(row)
        preview = Card("Pen activity")
        self.preview = DotGrid()
        preview.layout.addWidget(self.preview, 1)
        layout.addWidget(preview, 1)
        self.stack.addWidget(page)

    def _make_mapping(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(16)
        card = Card("Positioning mode")
        self.mode_group = QButtonGroup(self)
        modes = QHBoxLayout()
        for label in ("Absolute", "Relative"):
            radio = QRadioButton(label)
            radio.setChecked(label == "Absolute")
            radio.toggled.connect(lambda checked, value=label: self.set_mode(value) if checked else None)
            self.mode_group.addButton(radio); modes.addWidget(radio)
        card.layout.addLayout(modes)
        info = QLabel("Absolute maps tablet coordinates to the selected monitor. Relative moves the cursor by the pen's movement delta.")
        info.setWordWrap(True); info.setObjectName("muted"); card.layout.addWidget(info)
        layout.addWidget(card)
        monitor = Card("Display target")
        self.monitor_combo = QComboBox()
        self.monitor_combo.currentIndexChanged.connect(self.set_target_screen)
        monitor.layout.addWidget(self.monitor_combo)
        layout.addWidget(monitor)
        note = QLabel("The selected monitor is used for absolute positioning. TabGO does not create or modify displays.")
        note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(note)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _make_pen(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(16)
        pressure = Card("Pressure telemetry")
        self.pen_pressure_label = QLabel("0%")
        self.pen_pressure_label.setObjectName("metric")
        self.sensitivity = QSlider(Qt.Horizontal); self.sensitivity.setRange(500,4000); self.sensitivity.setValue(1800)
        pressure.layout.addWidget(self.pen_pressure_label)
        pressure.layout.addWidget(QLabel("Relative cursor sensitivity"))
        pressure.layout.addWidget(self.sensitivity)
        layout.addWidget(pressure)
        status = Card("Pen capabilities")
        self.capability_text = QLabel("Waiting for Android stylus events.\n\nTabGO reads hover, contact, pressure, tilt and button state when exposed by the tablet. Windows PT_PEN injection: " + ("available" if self.synthetic_pen.available else "unavailable (mouse fallback)"))
        self.capability_text.setObjectName("muted"); self.capability_text.setWordWrap(True)
        status.layout.addWidget(self.capability_text)
        layout.addWidget(status)
        warning = QLabel("Pressure is currently received and displayed as telemetry. Pressure-sensitive drawing in Windows apps requires a dedicated Windows pen digitizer/HID driver; this preview does not pretend mouse input is pressure input.")
        warning.setObjectName("notice"); warning.setWordWrap(True); layout.addWidget(warning)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _make_diagnostics(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(16)
        grid = QGridLayout()
        self.diag_labels = {}
        for i, (key, title) in enumerate([("x","X coordinate"),("y","Y coordinate"),("pressure","Pressure"),("action","Pen state"),("tilt","Tilt"),("rate","Event rate")]):
            card = Card(title)
            val = QLabel("—"); val.setObjectName("metric")
            card.layout.addWidget(val); self.diag_labels[key] = val
            grid.addWidget(card, i//2, i%2)
        layout.addLayout(grid)
        log = Card("Connection log")
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(150)
        log.layout.addWidget(self.log); layout.addWidget(log)
        layout.addStretch(1)
        self.stack.addWidget(page)

    def _make_settings(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0,0,0,0); layout.setSpacing(16)
        card = Card("USB connection")
        self.device_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh devices")
        self.refresh_button.clicked.connect(self.refresh_device_list)
        card.layout.addWidget(QLabel("Android device"))
        card.layout.addWidget(self.device_combo)
        card.layout.addWidget(self.refresh_button)
        layout.addWidget(card)
        info = Card("About TabGO")
        label = QLabel("TabGO is an independent graphics-tablet input bridge. It does not install a virtual monitor or modify your existing pen-display drivers.")
        label.setWordWrap(True); label.setObjectName("muted"); info.layout.addWidget(label)
        layout.addWidget(info); layout.addStretch(1)
        self.stack.addWidget(page)

    def show_page(self, index):
        self.stack.setCurrentIndex(index)
        self.page_title.setText(["Dashboard","Mapping","Pen","Diagnostics","Settings"][index])
        for i, b in enumerate(self.nav_buttons): b.setChecked(i == index)

    def _load_screens(self):
        self.monitor_combo.clear()
        for i, screen in enumerate(QGuiApplication.screens()):
            g = screen.geometry()
            self.monitor_combo.addItem(f"{'Primary · ' if screen == QGuiApplication.primaryScreen() else ''}{screen.name()}  ({g.width()} × {g.height()})", i)
        if self.monitor_combo.count() == 0: self.monitor_combo.addItem("Primary display", 0)

    def refresh_device_list(self):
        current = self.device_combo.currentData()
        adb = shutil.which("adb")
        self.device_combo.clear()
        if not adb:
            self.device_combo.addItem("ADB not found (install Platform Tools)", "")
            return
        try:
            result = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=3)
            for line in result.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    self.device_combo.addItem(parts[0], parts[0])
            if self.device_combo.count() == 0: self.device_combo.addItem("No authorized USB devices", "")
            idx = self.device_combo.findData(current)
            if idx >= 0: self.device_combo.setCurrentIndex(idx)
        except Exception:
            self.device_combo.addItem("Unable to query ADB", "")

    def toggle_connection(self):
        enabled = self.connect_button.text() != "Disconnect"
        serial = self.device_combo.currentData() or ""
        self.worker.set_enabled(enabled, serial)
        self.connect_button.setText("Disconnect" if enabled else "Connect tablet")
        if enabled: self.add_log("Starting USB connection…")
        else:
            self.mouse.reset()
            if self.pen_down: self.mouse.button(False); self.pen_down = False

    def set_status(self, message, kind):
        self.connection_big.setText(message)
        self.connection_detail.setText("USB pen-event bridge")
        self.connection_badge.setText("●  " + ("CONNECTED" if kind == "good" else "DISCONNECTED" if kind == "muted" else "SEARCHING"))
        self.connection_badge.setObjectName({"good":"badgeGood","bad":"badgeBad","warn":"badgeWarn","muted":"badgeMuted"}.get(kind,"badgeMuted"))
        self.connection_badge.style().unpolish(self.connection_badge); self.connection_badge.style().polish(self.connection_badge)
        self.side_status.setText("●  " + ("CONNECTED" if kind == "good" else "DISCONNECTED" if kind == "muted" else "SEARCHING"))
        self.side_status.setStyleSheet("color:"+ (GREEN if kind=="good" else AMBER if kind=="warn" else MUTED))
        self.add_log(message)

    def set_mode(self, value):
        self.mode = value
        self.mouse.reset()
        self.add_log("Positioning mode: " + value)

    def set_target_screen(self, index):
        self.target_screen = index
        self.mouse.reset()

    def _screen_rect(self):
        screens = QGuiApplication.screens()
        if not screens: return (0,0,1920,1080)
        s = screens[min(self.target_screen, len(screens)-1)].geometry()
        return (s.x(), s.y(), s.width(), s.height())

    def on_pen_event(self, event):
        self.last_event = event
        x = float(event.get("x", 0.0)); y = float(event.get("y", 0.0))
        pressure = max(0.0, min(1.0, float(event.get("pressure", 0.0))))
        action = str(event.get("action", "move")).lower()
        contact = action in ("down", "move") and bool(event.get("contact", action == "down" or pressure > 0))
        self.pressure_number.setText(f"{pressure*100:.0f}%")
        self.pen_pressure_label.setText(f"{pressure*100:.0f}%")
        self.pressure_bar.setValue(int(pressure*100))
        self.pressure_state.setText("Pen touching" if contact else "Pen hovering")
        self.preview.set_pen(x, y, contact)
        self.diag_labels["x"].setText(f"{x:.4f}")
        self.diag_labels["y"].setText(f"{y:.4f}")
        self.diag_labels["pressure"].setText(f"{pressure*100:.1f}%")
        self.diag_labels["action"].setText(action.upper())
        self.diag_labels["tilt"].setText(f"{float(event.get('tiltX',0)):.2f}, {float(event.get('tiltY',0)):.2f}")
        self.diag_labels["rate"].setText(f"{event.get('rate', '—')}")
        injected = self.synthetic_pen.send(
            x, y, pressure, action, self._screen_rect(), self.mode,
            self.sensitivity.value(), event.get("tiltX", 0), event.get("tiltY", 0),
            event.get("tool", "stylus")
        )
        if not injected:
            if self.mode == "Absolute":
                self.mouse.move_absolute(x, y, self._screen_rect())
            else:
                self.mouse.move_relative(x, y, self.sensitivity.value())
            if action == "down" and not self.pen_down:
                self.mouse.button(True); self.pen_down = True
            elif action == "up" and self.pen_down:
                self.mouse.button(False); self.pen_down = False

    def add_log(self, message):
        if hasattr(self, "log"):
            self.log.append(time.strftime("%H:%M:%S") + "  " + message)

    def closeEvent(self, event):
        self.worker.set_enabled(False)
        self.worker.stop()
        if self.pen_down: self.mouse.button(False)
        self.synthetic_pen.close()
        event.accept()

def apply_style(app):
    app.setStyleSheet("""
    QWidget { background: #202225; color: #eef0f2; font-family: 'Segoe UI'; font-size: 10pt; }
    QFrame#sidebar { background: #191b1e; border: none; }
    QLabel#brand { color: #f3f4f6; font-size: 23pt; font-weight: 800; letter-spacing: 3px; }
    QLabel#brandSub, QLabel#eyebrow { color: #858d98; font-size: 8pt; font-weight: 700; letter-spacing: 1.4px; }
    QLabel#pageTitle { font-size: 22pt; font-weight: 650; }
    QLabel#muted { color: #969da7; }
    QLabel#metric { color: #f5f6f7; font-size: 23pt; font-weight: 650; }
    QLabel#sideStatus { color: #9aa1ab; font-size: 9pt; font-weight: 700; }
    QFrame#card { background: #292c30; border: 1px solid #363a40; border-radius: 13px; }
    QPushButton#nav { text-align: left; padding: 12px 14px; border: 0; border-radius: 8px; color: #aeb4bd; background: transparent; }
    QPushButton#nav:hover { background: #292c30; color: #ffffff; }
    QPushButton#nav:checked { background: #30343a; color: #ffffff; border-left: 3px solid #8b9cff; }
    QPushButton#primary { background: #8b9cff; color: #17191d; border: 0; border-radius: 8px; padding: 11px 15px; font-weight: 700; }
    QPushButton#primary:hover { background: #a5b1ff; }
    QPushButton { background: #353940; border: 1px solid #454a52; border-radius: 7px; padding: 8px 12px; }
    QPushButton:hover { background: #41464e; }
    QComboBox, QTextEdit { background: #1d1f22; border: 1px solid #3b4047; border-radius: 7px; padding: 8px; }
    QComboBox QAbstractItemView { background: #292c30; selection-background-color: #454b55; }
    QProgressBar { background: #1c1e21; border: none; border-radius: 5px; height: 9px; }
    QProgressBar::chunk { background: #8b9cff; border-radius: 5px; }
    QSlider::groove:horizontal { height: 5px; background: #454a52; border-radius: 2px; }
    QSlider::handle:horizontal { background: #a5b1ff; width: 15px; margin: -5px 0; border-radius: 7px; }
    QRadioButton { spacing: 8px; padding: 8px; }
    QRadioButton::indicator { width: 16px; height: 16px; }
    QLabel#badgeGood { color: #57d69a; background: #23382f; padding: 8px 12px; border-radius: 10px; font-weight: 700; }
    QLabel#badgeWarn { color: #e8bd69; background: #3b3324; padding: 8px 12px; border-radius: 10px; font-weight: 700; }
    QLabel#badgeBad { color: #ed7777; background: #3d2828; padding: 8px 12px; border-radius: 10px; font-weight: 700; }
    QLabel#badgeMuted { color: #a2a8b1; background: #30343a; padding: 8px 12px; border-radius: 10px; font-weight: 700; }
    QLabel#notice { background: #3b3324; color: #e8bd69; border: 1px solid #59492c; border-radius: 9px; padding: 12px; }
    """)
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_style(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
