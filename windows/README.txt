TABGO GRAPHICS TABLET - DEVELOPMENT PREVIEW

This branch is the new graphics-tablet direction. It is independent of the old
screen-mirroring implementation. No video streaming or virtual monitor is used.

BUILD OUTPUTS
- TabGO.exe: standalone Windows desktop UI.
- TabGO-Android.apk: native Android stylus capture application.

USB CONNECTION
1. Install Android SDK Platform Tools (adb) on Windows and make adb available on PATH.
2. Enable Developer options > USB debugging on the Android tablet.
3. Connect the tablet by USB and approve the computer's debugging prompt.
4. Install and open TabGO-Android.apk on the tablet.
5. Launch TabGO.exe on Windows and press Connect tablet.
6. Select the connected device under Settings if more than one device is attached.

The Android app opens a local TCP pen-event endpoint. The Windows app uses
'adb forward' to tunnel that endpoint over the USB debugging connection.
No Wi-Fi or video transport is involved.

CURRENT IMPLEMENTATION SCOPE
- Android stylus hover, contact, position, pressure, tilt and button-state capture
  when exposed by the tablet's Android input stack.
- USB event transport over ADB forwarding.
- Windows dark-themed Python/PySide6 application.
- Absolute mapping to a selected monitor and relative mouse movement.
- Live pressure and pen-event diagnostics.

WINDOWS PEN INPUT
The Windows app uses Microsoft's documented CreateSyntheticPointerDevice /
InjectSyntheticPointerInput PT_PEN API when available (Windows 10 1809+).
It sends position, hover/contact state, pressure and tilt as synthetic pen
pointer events, without installing a virtual HID or kernel driver.
Compatibility with individual drawing applications must be verified on the
actual PC; apps that ignore synthetic pen input may need a different backend.
The app falls back to mouse movement if PT_PEN injection is unavailable.

COMPATIBILITY NOTES
- Windows 10/11 x64.
- Android 8.0+ (API 26+).
- Actual stylus hover and pressure availability depends on the tablet and pen.
- This software does not uninstall, disable, or modify other tablet drivers.
- No virtual display driver is installed.
