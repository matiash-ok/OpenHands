---
name: android-device
description: Build, install, run and inspect Android apps on the user's real phone (a Samsung Galaxy Z Flip) from this machine, through the adb server on the host. Use when a task says to test on the phone, on a real device, on the Z Flip, or to develop or debug an Android feature on hardware.
triggers:
  - z flip
  - real device
  - adb
---

# android-device

The user's phone is attached to the host, not to this machine. The host runs the
adb server; you use it over the network. You never start an adb server here.

## Connect

```bash
command -v adb >/dev/null || { sudo apt-get update && sudo apt-get install -y adb; }
export ADB_SERVER_SOCKET=tcp:172.30.0.1:5037
unset LD_LIBRARY_PATH   # this machine's shell sets one that breaks adb's libraries
adb devices -l
```

Installing adb on this machine is always fine; "do not install anything" from
the user is about the phone.

Put the `export` and the `unset` in every shell you use adb from (or in `~/.bashrc`).

- A device listed as `device`: ready.
- `unauthorized` or `offline`: tell the user to unlock the phone and accept the debugging prompt.
- Empty list, or `cannot connect to daemon`: the phone is not shared right now. Tell
  the user to turn on Wireless debugging on the phone and run
  `sudo agente-pc telefono on IP:PORT` on the host. Do not
  try to work around it.

Never run `adb kill-server`, `adb start-server`, `adb tcpip`, `adb root` or
`adb reboot` (any form): the server and the phone belong to the user.

## Build and install

This machine starts without the Android SDK. Install what the project needs
(a JDK, the SDK command-line tools, the platforms and build-tools its Gradle
files ask for) under `$HOME`, which is kept between sessions of this
conversation. Then:

```bash
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n <applicationId>/<activity>
```

For React Native or Expo, the phone must reach the dev server on this machine:
`adb reverse tcp:8081 tcp:8081` does not cross to this machine, so build a
release-like bundle into the APK, or ask the user how they want it served.

## Look at the result

```bash
adb logcat -d -t 300 '*:W'                        # recent warnings and errors
adb logcat -d --pid=$(adb shell pidof -s <applicationId>)
adb shell dumpsys SurfaceFlinger --display-id        # ids of the two displays
adb exec-out screencap -p -d <display-id> > /workspace/screen.png  # then view the image
adb shell uiautomator dump /sdcard/ui.xml && adb exec-out cat /sdcard/ui.xml
adb shell input tap <x> <y>; adb shell input text 'hello'; adb shell input keyevent BACK
adb shell wm size; adb shell dumpsys window displays | grep -i fold   # screen and fold state
```

Always pass `-d` to `screencap`: with two displays, without it adb puts a
warning line before the PNG and the file is corrupt.

The Z Flip has two displays (cover and main) and a fold state. Check which
display the app is on before judging a layout, and test both states when the
feature depends on it. Ask the user to fold or unfold: you cannot.

## Limits

- This is a personal phone. Touch only the app under development: install,
  start, stop and clear **its** data (`adb shell pm clear <applicationId>`).
- Do not uninstall or change other apps, change system settings, or read
  personal data (photos, messages, contacts, accounts, other apps' storage).
- Only one phone is shared. If several agents use it, take turns: do not assume
  the app on screen is yours; check with
  `adb shell dumpsys activity activities | grep -m1 ResumedActivity`.
- Report what you verified on the device and what you could not (anything
  needing a human hand: folding, biometrics, camera, physical buttons).
