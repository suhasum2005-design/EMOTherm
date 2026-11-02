"""Real OpenCV, framed serial, and vendor plugin capture drivers."""
import importlib
import os
import struct
import threading
import cv2
import numpy as np


class Camera:
    def __init__(self):
        self.driver = os.getenv('CAMERA_DRIVER', 'opencv')
        self.lock = threading.Lock()
        self.device = None

    def open(self):
        if self.device is not None:
            return
        if self.driver == 'opencv':
            source = os.getenv('CAMERA_SOURCE', '0')
            self.device = cv2.VideoCapture(int(source) if source.isdigit() else source)
            if not self.device.isOpened():
                self.close()
                raise RuntimeError('Camera unavailable. Check CAMERA_SOURCE and driver access.')
        elif self.driver == 'serial':
            import serial
            self.device = serial.Serial(os.getenv('CAMERA_SERIAL_PORT', 'COM3'), int(os.getenv('CAMERA_BAUD', '115200')), timeout=2)
        elif self.driver == 'vendor':
            module_name = os.getenv('CAMERA_PLUGIN', '')
            if not module_name:
                raise RuntimeError('Set CAMERA_PLUGIN to your installed vendor adapter module.')
            # Plugin's open_camera() returns a device with read()->(bool, ndarray), release().
            self.device = importlib.import_module(module_name).open_camera()
        else:
            raise RuntimeError('Unsupported CAMERA_DRIVER')

    def read_exact(self, count):
        result = bytearray()
        while len(result) < count:
            chunk = self.device.read(count - len(result))
            if not chunk:
                raise RuntimeError('Thermal serial camera timed out.')
            result.extend(chunk)
        return bytes(result)

    def frame(self):
        with self.lock:
            self.open()
            if self.driver == 'serial':
                # Explicit framing: ETH1 + uint32 little-endian byte length + uint16 pixels.
                # Other vendor serial protocols need an adapter, not guessed packet parsing.
                window = bytearray()
                for _ in range(65536):
                    window += self.read_exact(1)
                    window = window[-4:]
                    if window == b'ETH1':
                        break
                else:
                    raise RuntimeError('Serial stream does not use the documented ETH1 protocol.')
                width = int(os.getenv('CAMERA_WIDTH', '80'))
                height = int(os.getenv('CAMERA_HEIGHT', '60'))
                length = struct.unpack('<I', self.read_exact(4))[0]
                if length != width * height * 2 or length > 4_000_000:
                    raise RuntimeError('Invalid serial frame dimensions.')
                gray = np.frombuffer(self.read_exact(length), dtype='<u2').reshape(height, width)
                gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            else:
                ok, frame = self.device.read()
                if not ok or frame is None:
                    raise RuntimeError('No frame received from camera.')
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
                gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
            # Transmit grayscale inference data and a separately colorized display preview.
            display = cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)
            ok, raw = cv2.imencode('.png', gray)
            ok2, preview = cv2.imencode('.jpg', display)
            if not ok or not ok2:
                raise RuntimeError('Camera encoding failed.')
            return raw.tobytes(), preview.tobytes()

    def close(self):
        if self.device is not None:
            if hasattr(self.device, 'release'):
                self.device.release()
            else:
                self.device.close()
        self.device = None
