"""
AGI Android MCP Server — control any Android device via ADB.

All device interaction goes through `adb` subprocess calls.
No proprietary dependencies, works with any Android phone that has USB debugging enabled.
"""

import base64
import os
import shutil
import subprocess
import time

from mcp.server.fastmcp import FastMCP, Image

# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

ADB = os.environ.get("ADB_PATH", shutil.which("adb") or "adb")
SERIAL = os.environ.get("ADB_SERIAL", "")


def _adb(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Run an adb command and return the CompletedProcess."""
    cmd = [ADB]
    if SERIAL:
        cmd += ["-s", SERIAL]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _shell(*args: str, timeout: float = 10.0) -> str:
    """Run `adb shell <args>` and return stdout as a stripped string."""
    r = _adb("shell", *args, timeout=timeout)
    return r.stdout.decode("utf-8", errors="replace").strip()


def _check_connection() -> str:
    """Verify an ADB device is connected and reachable."""
    r = _adb("devices", timeout=5.0)
    output = r.stdout.decode("utf-8", errors="replace")
    lines = [l for l in output.strip().splitlines()[1:] if l.strip()]

    if not lines:
        raise RuntimeError(
            "No ADB devices found. Connect a device with USB debugging enabled "
            "and run 'adb devices' to verify."
        )

    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 2:
            serial, state = parts[0], parts[1]
            if SERIAL and serial != SERIAL:
                continue
            if state == "offline":
                raise RuntimeError(f"Device {serial} is offline.")
            if state == "device":
                return serial

    if SERIAL:
        raise RuntimeError(
            f"Device with serial '{SERIAL}' not found. "
            f"Available devices:\n{output}"
        )
    raise RuntimeError(f"No usable ADB device found. Output:\n{output}")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "AGI Android MCP",
    instructions="Control any Android phone via ADB — tap, swipe, type, screenshot, and more.",
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def screenshot() -> Image:
    """Take a screenshot of the Android screen. Returns the current screen as a PNG image."""
    _check_connection()
    r = _adb("exec-out", "screencap", "-p", timeout=15.0)
    if r.returncode != 0:
        raise RuntimeError(
            f"screencap failed: {r.stderr.decode('utf-8', errors='replace')}"
        )
    png_bytes = r.stdout
    if not png_bytes or len(png_bytes) < 8:
        raise RuntimeError("screencap returned empty data")
    return Image(data=png_bytes, format="png")


@mcp.tool()
def get_screen_size() -> dict:
    """Get the physical screen size of the Android device in pixels."""
    _check_connection()
    output = _shell("wm", "size")
    # Example: "Physical size: 1080x2400"
    for line in output.splitlines():
        if "Physical size" in line:
            dims = line.split(":")[-1].strip()
            w, h = dims.split("x")
            return {"width": int(w), "height": int(h)}
    # Fallback: try parsing override or whatever is there
    if "x" in output:
        parts = output.strip().splitlines()[-1]
        dims = parts.split(":")[-1].strip() if ":" in parts else parts.strip()
        if "x" in dims:
            w, h = dims.split("x")
            return {"width": int(w.strip()), "height": int(h.strip())}
    raise RuntimeError(f"Could not parse screen size from: {output}")


@mcp.tool()
def tap(x: int, y: int) -> str:
    """Tap at (x, y) pixel coordinates on the screen."""
    _check_connection()
    _shell("input", "tap", str(x), str(y))
    return f"Tapped ({x}, {y})"


@mcp.tool()
def double_tap(x: int, y: int) -> str:
    """Double-tap at (x, y) pixel coordinates on the screen."""
    _check_connection()
    _shell("input", "tap", str(x), str(y))
    time.sleep(0.1)
    _shell("input", "tap", str(x), str(y))
    return f"Double-tapped ({x}, {y})"


@mcp.tool()
def long_press(x: int, y: int) -> str:
    """Long-press at (x, y) pixel coordinates (holds for 1 second)."""
    _check_connection()
    _shell("input", "swipe", str(x), str(y), str(x), str(y), "1000")
    return f"Long-pressed ({x}, {y})"


@mcp.tool()
def type_text(text: str) -> str:
    """Type text into the currently focused input field.

    Handles spaces and special characters automatically.
    """
    _check_connection()
    # ADB input text doesn't handle spaces well — replace with %s
    # Also escape shell-special characters
    escaped = text.replace("\\", "\\\\")
    escaped = escaped.replace(" ", "%s")
    escaped = escaped.replace("'", "\\'")
    escaped = escaped.replace('"', '\\"')
    escaped = escaped.replace("&", "\\&")
    escaped = escaped.replace("|", "\\|")
    escaped = escaped.replace(";", "\\;")
    escaped = escaped.replace("(", "\\(")
    escaped = escaped.replace(")", "\\)")
    escaped = escaped.replace("<", "\\<")
    escaped = escaped.replace(">", "\\>")
    escaped = escaped.replace("`", "\\`")
    _shell("input", "text", escaped)
    return f"Typed: {text}"


@mcp.tool()
def press_key(key: str) -> str:
    """Press a key on the Android device.

    Supported keys: enter, backspace, delete, tab, space, home, back,
    menu, search, volume_up, volume_down, power, escape.
    """
    _check_connection()
    keymap = {
        "enter": "66",
        "backspace": "67",
        "delete": "112",
        "tab": "61",
        "space": "62",
        "home": "3",
        "back": "4",
        "menu": "82",
        "search": "84",
        "volume_up": "24",
        "volume_down": "25",
        "power": "26",
        "escape": "111",
    }
    keycode = keymap.get(key.lower())
    if keycode is None:
        # Try as raw KEYCODE_ value
        _shell("input", "keyevent", key)
        return f"Pressed key: {key}"
    _shell("input", "keyevent", keycode)
    return f"Pressed {key}"


@mcp.tool()
def swipe(direction: str, distance: int = 500, x: int = -1, y: int = -1) -> str:
    """Swipe the screen in a direction.

    Args:
        direction: One of "up", "down", "left", "right".
        distance: Swipe distance in pixels (default 500).
        x: Starting X coordinate. Defaults to screen center.
        y: Starting Y coordinate. Defaults to screen center.
    """
    _check_connection()
    # Get screen size for centering
    if x < 0 or y < 0:
        size = get_screen_size()
        if x < 0:
            x = size["width"] // 2
        if y < 0:
            y = size["height"] // 2

    direction = direction.lower()
    if direction == "up":
        ex, ey = x, y - distance
    elif direction == "down":
        ex, ey = x, y + distance
    elif direction == "left":
        ex, ey = x - distance, y
    elif direction == "right":
        ex, ey = x + distance, y
    else:
        raise ValueError(f"Invalid direction: {direction}. Use up/down/left/right.")

    _shell("input", "swipe", str(x), str(y), str(ex), str(ey), "300")
    return f"Swiped {direction} from ({x}, {y}) to ({ex}, {ey})"


@mcp.tool()
def drag(start_x: int, start_y: int, end_x: int, end_y: int) -> str:
    """Drag from (start_x, start_y) to (end_x, end_y) with a 300ms duration."""
    _check_connection()
    _shell(
        "input", "swipe",
        str(start_x), str(start_y),
        str(end_x), str(end_y),
        "300",
    )
    return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"


@mcp.tool()
def press_home() -> str:
    """Press the Home button."""
    _check_connection()
    _shell("input", "keyevent", "KEYCODE_HOME")
    return "Pressed Home"


@mcp.tool()
def press_back() -> str:
    """Press the Back button."""
    _check_connection()
    _shell("input", "keyevent", "KEYCODE_BACK")
    return "Pressed Back"


@mcp.tool()
def open_notifications() -> str:
    """Open the notification shade."""
    _check_connection()
    _shell("cmd", "statusbar", "expand-notifications")
    return "Opened notifications"


@mcp.tool()
def open_quick_settings() -> str:
    """Open the quick settings panel."""
    _check_connection()
    _shell("cmd", "statusbar", "expand-settings")
    return "Opened quick settings"


@mcp.tool()
def launch_app(package: str) -> str:
    """Launch an Android app by its package name (e.g. com.android.chrome)."""
    _check_connection()
    output = _shell(
        "monkey", "-p", package,
        "-c", "android.intent.category.LAUNCHER", "1",
    )
    if "No activities found" in output:
        raise RuntimeError(
            f"Could not launch '{package}': no launcher activity found. "
            f"Check the package name with list_installed_apps()."
        )
    return f"Launched {package}"


@mcp.tool()
def get_current_app() -> str:
    """Get the currently visible app (package name and activity)."""
    _check_connection()
    output = _shell("dumpsys", "activity", "activities", timeout=5.0)
    for line in output.splitlines():
        if "mResumedActivity" in line or "ResumedActivity" in line:
            return line.strip()
    return "Could not determine current activity"


@mcp.tool()
def list_installed_apps() -> list[str]:
    """List third-party installed apps (package names)."""
    _check_connection()
    output = _shell("pm", "list", "packages", "-3", timeout=10.0)
    packages = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            packages.append(line[len("package:"):])
    return sorted(packages)


@mcp.tool()
def shell(command: str) -> str:
    """Run an arbitrary ADB shell command and return its output.

    Use this for anything not covered by the other tools.
    """
    _check_connection()
    result = _shell(command, timeout=15.0)
    return result


@mcp.tool()
def get_device_info() -> dict:
    """Get device information: screen size, Android version, model, and battery level."""
    _check_connection()

    # Screen size
    screen = {}
    try:
        screen = get_screen_size()
    except Exception as e:
        screen = {"error": str(e)}

    # Android version
    android_version = _shell("getprop", "ro.build.version.release")

    # Device model
    model = _shell("getprop", "ro.product.model")

    # Manufacturer
    manufacturer = _shell("getprop", "ro.product.manufacturer")

    # Battery
    battery_output = _shell("dumpsys", "battery")
    battery = {}
    for line in battery_output.splitlines():
        line = line.strip()
        if line.startswith("level:"):
            battery["level"] = int(line.split(":")[1].strip())
        elif line.startswith("status:"):
            status_code = int(line.split(":")[1].strip())
            battery["status"] = {
                1: "unknown",
                2: "charging",
                3: "discharging",
                4: "not_charging",
                5: "full",
            }.get(status_code, str(status_code))

    return {
        "screen": screen,
        "android_version": android_version,
        "model": model,
        "manufacturer": manufacturer,
        "battery": battery,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
