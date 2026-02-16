# AGI Android MCP Server

Control any Android phone from Claude, Cursor, or any MCP client — via ADB.

```
LLM  -->  MCP (stdio)  -->  agi-android-mcp  -->  ADB  -->  Android Device
```

No proprietary dependencies. Works with any Android phone that has USB debugging enabled.

## Prerequisites

- **Python 3.10+**
- **ADB** installed and in PATH (`brew install android-platform-tools` on macOS)
- **USB debugging** enabled on your Android phone (Settings > Developer options > USB debugging)
- Phone connected via USB and authorized (`adb devices` should show your device)

## Quick Start

### 1. Install

```bash
git clone https://github.com/agi-inc/agi-android-mcp.git
cd agi-android-mcp
pip install .
```

### 2. Connect your phone

```bash
# Verify ADB sees your device
adb devices
# Should show something like:
#   XXXXXXXXXXXXXX    device
```

### 3. Add to Claude Code

Add to `~/.claude/claude_code_config.json`:

```json
{
  "mcpServers": {
    "android": {
      "command": "agi-android-mcp"
    }
  }
}
```

Restart Claude Code. You'll see the Android tools available. Just tell Claude:

> "Take a screenshot of my phone"

> "Open Chrome and search for the weather"

> "Launch Settings and turn on dark mode"

Claude will take screenshots, reason about the UI, and tap/type/swipe to accomplish the task.

### 3b. Add to Cursor (alternative)

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "android": {
      "command": "agi-android-mcp"
    }
  }
}
```

### 3c. Add to any MCP client

The server uses stdio transport. Just run `agi-android-mcp` as the command — it speaks MCP over stdin/stdout.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADB_PATH` | Auto-detected | Path to `adb` binary |
| `ADB_SERIAL` | (none) | Target a specific device by serial number |

If you have multiple devices connected, set `ADB_SERIAL` to target a specific one:

```json
{
  "mcpServers": {
    "android": {
      "command": "agi-android-mcp",
      "env": {
        "ADB_SERIAL": "XXXXXXXXXXXXXX"
      }
    }
  }
}
```

## Tools (18)

| Tool | Description |
|------|-------------|
| `screenshot` | Take a screenshot, returned as PNG image |
| `get_screen_size` | Get physical screen dimensions in pixels |
| `tap(x, y)` | Tap at pixel coordinates |
| `double_tap(x, y)` | Double-tap at pixel coordinates |
| `long_press(x, y)` | Long-press at pixel coordinates (1s hold) |
| `type_text(text)` | Type text into focused input field |
| `press_key(key)` | Press a key (enter, backspace, delete, tab, space, home, back, etc.) |
| `swipe(direction)` | Swipe up/down/left/right from screen center |
| `drag(start_x, start_y, end_x, end_y)` | Drag between two points |
| `press_home()` | Press the Home button |
| `press_back()` | Press the Back button |
| `open_notifications()` | Open the notification shade |
| `open_quick_settings()` | Open quick settings panel |
| `launch_app(package)` | Launch an app by package name |
| `get_current_app()` | Get the currently visible app/activity |
| `list_installed_apps()` | List third-party installed packages |
| `shell(command)` | Run any ADB shell command |
| `get_device_info()` | Get device model, Android version, screen size, battery |

## Demo

The included `demo.py` runs an agentic loop: screenshot -> Claude decides action -> execute via ADB -> repeat.

```bash
pip install anthropic
ANTHROPIC_API_KEY=sk-... python demo.py "Open Chrome and search for cats"
```

Options:

```bash
python demo.py "Open Settings" --model claude-sonnet-4-5-20250929 --steps 30
```

## How It Works

1. The MCP server starts and communicates over stdio (standard MCP transport)
2. When an MCP client (Claude Code, Cursor, etc.) calls a tool, the server translates it into an `adb` subprocess call
3. Screenshots use `adb exec-out screencap -p` to capture the screen as PNG
4. Input actions use `adb shell input tap/swipe/text/keyevent`
5. App management uses `adb shell am`, `adb shell pm`, `adb shell monkey`

## Development

```bash
# Install in development mode
pip install -e .

# Verify tools are registered
python -c "from agi_android_mcp.server import mcp; print(len(mcp._tool_manager._tools), 'tools')"
```

## License

MIT
