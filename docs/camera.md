# Camera integration contract

The browser path uses getUserMedia, an actual video stream, and PNG canvas capture. The Python bridge runs a real acquisition loop and streams preview JPEGs over a session-authenticated WebSocket. Capture submits the latest user's original grayscale PNG, never a fake image or a synthetic classification.

## Supported serial wire format

```text
4 bytes       ASCII ETH1
4 bytes       unsigned little-endian payload byte length
W × H × 2     unsigned 16-bit little-endian thermal samples, row-major
```

Configure W/H with CAMERA_WIDTH and CAMERA_HEIGHT. The parser resynchronizes on ETH1, bounds the payload, reads full packets, rejects dimension mismatches, and uses timeouts. Set baud rate appropriate to frame size and desired frame rate. An 80×60×2-byte frame at 115200 baud takes about 0.84 seconds before overhead; do not expect 8 FPS from that connection.

This protocol is for compatible devices/firmware or an adapter emitting ETH1; it is not a universal FLIR/Seek/Lepton protocol. Match vendor transport, radiometry, pixel endianness and sensor calibration to its documentation. The parser normalizes uint16 samples to uint8 for the current model; absolute temperature is not modeled.

## Vendor adapter interface

Install the vendor SDK in the backend environment. Write `your_adapter.py`:

```python
def open_camera():
    # Open the actual vendor device using its SDK.
    # Return an object whose read() is (ok, numpy.ndarray) and release() closes it.
    return VendorCapture()
```

Set `CAMERA_DRIVER=vendor` and `CAMERA_PLUGIN=your_adapter`. The read array may be grayscale uint8/uint16 or OpenCV BGR uint8. The driver normalizes and encodes it. The example describes the interface rather than pretending an unknown SDK is implemented.

## Hardware checklist

- Verify thermal data rather than ordinary RGB feed; allow UVC permission and select correct device.
- Confirm CAMERA_SOURCE opens via OpenCV for bridge capture.
- Serial: verify actual firmware packet format, COM port, baud, resolution, byte order and timeout.
- Capture on both paths and verify records report uvc/bridge correctly.
- Disconnect hardware midstream; UI should explain the failure and disable capture.
- Close the page; stream tracks and socket are stopped, and server clears recent frames.

Software tests cover a generated video through the real OpenCV driver, framed serial parsing with a byte-stream test double, authenticated WebSocket streaming, and end-to-end server bridge capture. Physical thermal camera testing remains required.
