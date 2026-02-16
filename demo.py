#!/usr/bin/env python3
"""
AGI Android MCP Demo — Let Claude drive your phone via ADB.

An agentic loop: screenshot -> Claude decides action -> execute via ADB -> repeat.

Usage:
    pip install anthropic
    ANTHROPIC_API_KEY=sk-... python demo.py "Open Chrome and search for cats"

Prerequisites:
    1. ADB installed and in PATH
    2. Android device connected with USB debugging enabled
    3. Run 'adb devices' to verify connectivity
"""

import argparse
import base64
import os
import shutil
import subprocess
import sys
import time

try:
    import anthropic
except ImportError:
    print("Error: 'anthropic' package required. Install with: pip install anthropic")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Colors for terminal output
# ---------------------------------------------------------------------------


class C:
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    RESET = "\033[0m"


BANNER = f"""{C.CYAN}{C.BOLD}
    ___   ____________   ___              __           _     __
   /   | / ____/  _/  | / / /___ ___  __/ /________  (_)___/ /
  / /| |/ / __ / // /| |/ / __  / __|/ / __  / ___/ / / __  /
 / ___ / /_/ // // ___ / / /_/ / /  / / /_/ / /  / / / /_/ /
/_/  |_\\____/___/_/  |_/_/\\__,_/_/  /_/\\____/_/  /_/_/\\__,_/
{C.RESET}{C.DIM}
            Claude x ADB — Android MCP Demo
{C.RESET}"""

# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------

ADB = os.environ.get("ADB_PATH", shutil.which("adb") or "adb")
SERIAL = os.environ.get("ADB_SERIAL", "")


def _adb(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    cmd = [ADB]
    if SERIAL:
        cmd += ["-s", SERIAL]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _shell(*args: str, timeout: float = 10.0) -> str:
    r = _adb("shell", *args, timeout=timeout)
    return r.stdout.decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Tools for Claude
# ---------------------------------------------------------------------------

SCREEN_W, SCREEN_H = 0, 0

TOOLS = [
    {
        "name": "screenshot",
        "description": "Take a screenshot of the Android screen. Call this to see what's on screen.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "tap",
        "description": "Tap at (x, y) pixel coordinates on the screen.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "X coordinate in pixels"},
                "y": {"type": "number", "description": "Y coordinate in pixels"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into the currently focused input field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "swipe",
        "description": "Swipe the screen in a direction (up/down/left/right).",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "press_key",
        "description": "Press a key: enter, back, home, backspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": ["enter", "back", "home", "backspace"],
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "launch_app",
        "description": "Launch an Android app by package name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "package": {"type": "string", "description": "e.g. com.android.chrome"},
            },
            "required": ["package"],
        },
    },
    {
        "name": "long_press",
        "description": "Long-press at (x, y) pixel coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "done",
        "description": "Call this when the task is complete. Include a summary of what you did.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was accomplished"},
            },
            "required": ["summary"],
        },
    },
]


# ---------------------------------------------------------------------------
# Pretty output helpers
# ---------------------------------------------------------------------------


def log_step(step: int, max_steps: int):
    bar_len = 30
    filled = int(bar_len * step / max_steps)
    bar = "=" * filled + "-" * (bar_len - filled)
    print(f"\n{C.BLUE}{C.BOLD}[{bar}] Step {step}/{max_steps}{C.RESET}")


def log_thinking(text: str):
    for line in text.split("\n"):
        print(f"  {C.DIM}{line}{C.RESET}")


def log_action(name: str, args: dict):
    args_str = ""
    if name == "tap":
        args_str = f"({args['x']}, {args['y']})"
    elif name == "type_text":
        args_str = f'"{args["text"]}"'
    elif name == "swipe":
        args_str = args["direction"]
    elif name == "press_key":
        args_str = args["key"]
    elif name == "launch_app":
        args_str = args["package"]
    elif name == "long_press":
        args_str = f"({args['x']}, {args['y']})"
    elif name == "screenshot":
        args_str = "capturing..."
    elif name == "done":
        args_str = args.get("summary", "")[:60]
    print(f"  {C.YELLOW}{C.BOLD}{name}{C.RESET} {C.DIM}{args_str}{C.RESET}")


def log_result(name: str, elapsed_ms: int):
    print(f"  {C.GREEN}done{C.RESET} {C.DIM}({elapsed_ms}ms){C.RESET}")


# ---------------------------------------------------------------------------
# Tool execution via ADB
# ---------------------------------------------------------------------------


def exec_tool(name: str, args: dict) -> list:
    """Execute a tool call via ADB and return Anthropic content blocks."""

    if name == "screenshot":
        r = _adb("exec-out", "screencap", "-p", timeout=15.0)
        if r.returncode != 0 or not r.stdout:
            return [{"type": "text", "text": f"Screenshot failed: {r.stderr.decode()}"}]
        b64 = base64.standard_b64encode(r.stdout).decode("ascii")
        return [
            {"type": "text", "text": f"Here is the current screen ({SCREEN_W}x{SCREEN_H}):"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            },
        ]

    elif name == "tap":
        x, y = int(args["x"]), int(args["y"])
        _shell("input", "tap", str(x), str(y))
        return [{"type": "text", "text": f"Tapped ({x}, {y})"}]

    elif name == "type_text":
        text = args["text"]
        escaped = text.replace(" ", "%s")
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace('"', '\\"')
        escaped = escaped.replace("&", "\\&")
        escaped = escaped.replace("|", "\\|")
        escaped = escaped.replace(";", "\;")
        escaped = escaped.replace("(", "\\(")
        escaped = escaped.replace(")", "\\)")
        _shell("input", "text", escaped)
        return [{"type": "text", "text": f"Typed: {text}"}]

    elif name == "swipe":
        direction = args["direction"]
        cx, cy = SCREEN_W // 2, SCREEN_H // 2
        dist = int(0.35 * SCREEN_H)
        if direction == "up":
            ex, ey = cx, cy - dist
        elif direction == "down":
            ex, ey = cx, cy + dist
        elif direction == "left":
            ex, ey = cx - dist, cy
        elif direction == "right":
            ex, ey = cx + dist, cy
        else:
            return [{"type": "text", "text": f"Invalid direction: {direction}"}]
        _shell("input", "swipe", str(cx), str(cy), str(ex), str(ey), "300")
        return [{"type": "text", "text": f"Swiped {direction}"}]

    elif name == "press_key":
        key = args["key"]
        keymap = {"enter": "66", "backspace": "67", "back": "4", "home": "3"}
        keycode = keymap.get(key, key)
        _shell("input", "keyevent", keycode)
        return [{"type": "text", "text": f"Pressed {key}"}]

    elif name == "launch_app":
        package = args["package"]
        _shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
        return [{"type": "text", "text": f"Launched {package}"}]

    elif name == "long_press":
        x, y = int(args["x"]), int(args["y"])
        _shell("input", "swipe", str(x), str(y), str(x), str(y), "1000")
        return [{"type": "text", "text": f"Long-pressed ({x}, {y})"}]

    elif name == "done":
        return [{"type": "text", "text": args["summary"]}]

    return [{"type": "text", "text": f"Unknown tool: {name}"}]


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

SYSTEM = """\
You are an Android phone operator. You can see the screen via screenshots and \
interact using tap, type_text, swipe, press_key, launch_app, and long_press.

Screen coordinates are in pixels. The screen is {w}x{h}.

Strategy:
1. Always start by taking a screenshot to see the current state.
2. Decide on one action at a time.
3. After each action, take another screenshot to verify the result.
4. When the task is complete, call the `done` tool with a summary.

Be precise with coordinates — look carefully at the screenshot to identify \
where UI elements are before tapping.\
"""


def run(task: str, max_steps: int = 25, model: str = "claude-sonnet-4-5-20250929"):
    global SCREEN_W, SCREEN_H

    client = anthropic.Anthropic()

    # Check ADB connectivity
    print(f"  {C.DIM}Checking ADB connection...{C.RESET}")
    r = _adb("devices", timeout=5.0)
    output = r.stdout.decode("utf-8", errors="replace")
    device_lines = [l for l in output.strip().splitlines()[1:] if l.strip()]
    if not device_lines:
        print(f"  {C.RED}{C.BOLD}Error:{C.RESET} {C.RED}No ADB devices found.{C.RESET}")
        print(f"  Connect a device with USB debugging enabled and run 'adb devices'.")
        sys.exit(1)

    # Get screen size
    try:
        wm_output = _shell("wm", "size")
        for line in wm_output.splitlines():
            if "Physical size" in line:
                dims = line.split(":")[-1].strip()
                w, h = dims.split("x")
                SCREEN_W, SCREEN_H = int(w), int(h)
                break
        if SCREEN_W == 0:
            SCREEN_W, SCREEN_H = 1080, 2400
    except Exception:
        SCREEN_W, SCREEN_H = 1080, 2400

    print(f"  {C.GREEN}Connected{C.RESET} | Screen: {SCREEN_W}x{SCREEN_H}")
    print(f"  {C.DIM}Model: {model}{C.RESET}")
    print(f"  {C.MAGENTA}{C.BOLD}Task:{C.RESET} {task}")

    system_prompt = SYSTEM.format(w=SCREEN_W, h=SCREEN_H)
    messages = [{"role": "user", "content": f"Task: {task}"}]
    total_tokens = 0
    start_time = time.time()

    for step in range(1, max_steps + 1):
        log_step(step, max_steps)

        t0 = time.time()
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )
        api_ms = int((time.time() - t0) * 1000)
        total_tokens += response.usage.input_tokens + response.usage.output_tokens

        print(
            f"  {C.DIM}API: {api_ms}ms | tokens: "
            f"+{response.usage.input_tokens + response.usage.output_tokens}{C.RESET}"
        )

        # Process response
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Show Claude's thinking
        for block in assistant_content:
            if block.type == "text" and block.text:
                log_thinking(block.text)

        # Check stop
        if response.stop_reason == "end_turn":
            print(f"\n  {C.DIM}Claude finished (no more tool calls).{C.RESET}")
            break

        # Execute tool calls
        tool_results = []
        finished = False
        for block in assistant_content:
            if block.type != "tool_use":
                continue

            name = block.name
            args = block.input
            log_action(name, args)

            t0 = time.time()
            result_content = exec_tool(name, args)
            exec_ms = int((time.time() - t0) * 1000)
            log_result(name, exec_ms)

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_content,
                }
            )

            if name == "done":
                finished = True
                print(f"\n{C.GREEN}{C.BOLD}Task Complete{C.RESET}")
                print(f"  {args['summary']}")

        messages.append({"role": "user", "content": tool_results})

        if finished:
            break
    else:
        print(f"\n  {C.YELLOW}Reached max steps ({max_steps}).{C.RESET}")

    elapsed = time.time() - start_time
    print(f"\n{C.DIM}  {elapsed:.1f}s total | {total_tokens:,} tokens{C.RESET}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Let Claude drive your Android phone via ADB.",
        epilog='Example: python demo.py "Open Settings and enable dark mode"',
    )
    parser.add_argument("task", help="What you want Claude to do on the phone")
    parser.add_argument("--steps", type=int, default=25, help="Max steps (default 25)")
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-5-20250929",
        help="Anthropic model (default: claude-sonnet-4-5-20250929)",
    )
    args = parser.parse_args()

    print(BANNER)
    run(args.task, max_steps=args.steps, model=args.model)


if __name__ == "__main__":
    main()
