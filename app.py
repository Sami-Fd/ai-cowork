"""
AI Cowork — Screen reader + chat assistant.

Captures the real laptop screen via mss, reads text with tesseract OCR,
keeps an in-memory session history, and lets the user chat with an LLM
that knows what was on screen.

Supports: Ollama (local), OpenAI, Anthropic Claude.
"""

import io
import json
import logging
import os
import sys
import threading
import time
import webbrowser
from collections import deque

# Load .env file — handle PyInstaller bundle path
from dotenv import load_dotenv

def _resource_path(relative: str) -> str:
    """Get absolute path to a resource, works for dev and for PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)

# Try loading .env from CWD first, then from bundle
if os.path.exists(".env"):
    load_dotenv(".env")
elif os.path.exists(_resource_path(".env.example")):
    load_dotenv(_resource_path(".env.example"))
else:
    load_dotenv()

import mss
import pytesseract
import requests
from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("REASONING_MODEL", "qwen2.5:7b")
CAPTURE_INTERVAL = int(os.getenv("CAPTURE_INTERVAL", "5"))
HISTORY_SIZE = int(os.getenv("HISTORY_SIZE", "50"))
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# Cloud LLM config
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # ollama | openai | anthropic
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# Privacy filter — comma-separated window title substrings to exclude
PRIVACY_EXCLUDE = [
    s.strip().lower()
    for s in os.getenv("PRIVACY_EXCLUDE", "").split(",")
    if s.strip()
]

# Monitor selection (0 = full virtual screen, 1 = first monitor, etc.)
SELECTED_MONITOR = int(os.getenv("SELECTED_MONITOR", "0"))

# Tesseract path on Windows (default install location)
TESSERACT_OK = False
if os.name == "nt":
    _candidates = [
        os.getenv("TESSERACT_PATH", ""),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for tesseract_path in _candidates:
        if tesseract_path and os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            TESSERACT_OK = True
            break
else:
    # On Linux/Mac, assume it's in PATH
    import shutil
    TESSERACT_OK = shutil.which("tesseract") is not None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cowork")

# Setup state — app starts in setup mode until user completes onboarding
SETUP_COMPLETE = False


# ---------------------------------------------------------------------------
# Privacy — get active window title (Windows only)
# ---------------------------------------------------------------------------
def get_active_window_title() -> str:
    """Return the title of the foreground window (Windows)."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def is_private_window() -> bool:
    """Check if the current foreground window should be excluded."""
    if not PRIVACY_EXCLUDE:
        return False
    title = get_active_window_title().lower()
    return any(kw in title for kw in PRIVACY_EXCLUDE)


# ---------------------------------------------------------------------------
# LLM Backends
# ---------------------------------------------------------------------------
def chat_ollama(system: str, user_msg: str) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {"temperature": 0.3},
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "No response.")


def chat_openai(system: str, user_msg: str) -> str:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.3,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def chat_anthropic(system: str, user_msg: str) -> str:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user_msg}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def chat_llm(system: str, user_msg: str) -> str:
    """Route to the configured LLM provider."""
    provider = LLM_PROVIDER.lower()
    if provider == "openai" and OPENAI_API_KEY:
        return chat_openai(system, user_msg)
    elif provider == "anthropic" and ANTHROPIC_API_KEY:
        return chat_anthropic(system, user_msg)
    else:
        return chat_ollama(system, user_msg)


# ---------------------------------------------------------------------------
# Screen Reader (in-memory session history only)
# ---------------------------------------------------------------------------
class ScreenReader:
    def __init__(self):
        self.lock = threading.Lock()
        self.history: deque = deque(maxlen=HISTORY_SIZE)
        self.last_png: bytes = b""
        self.last_text: str = ""
        self._prev_text: str = ""
        self._running = False
        self._paused = False

    # -- capture ---------------------------------------------------------------
    def capture(self) -> Image.Image | None:
        try:
            with mss.mss() as sct:
                idx = SELECTED_MONITOR
                if idx < 0 or idx >= len(sct.monitors):
                    idx = 0
                monitor = sct.monitors[idx]
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            # keep a PNG copy for the dashboard
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            with self.lock:
                self.last_png = buf.getvalue()
            return img
        except Exception as e:
            log.error(f"Capture error: {e}")
            return None

    # -- OCR -------------------------------------------------------------------
    def ocr(self, img: Image.Image) -> str:
        try:
            w, h = img.size
            processed = img
            if w < 1920:
                processed = processed.resize((w * 2, h * 2), Image.LANCZOS)

            gray = processed.convert("L").filter(ImageFilter.SHARPEN)
            gray = ImageEnhance.Contrast(gray).enhance(1.8)

            text_normal = pytesseract.image_to_string(gray, config="--psm 3 --oem 3")
            text_inv = pytesseract.image_to_string(
                ImageOps.invert(gray), config="--psm 3 --oem 3"
            )
            raw = text_normal if len(text_normal) >= len(text_inv) else text_inv

            lines = []
            for line in raw.splitlines():
                line = line.strip()
                if len(line) < 3:
                    continue
                alnum = sum(1 for c in line if c.isalnum() or c.isspace())
                if alnum / len(line) < 0.5:
                    continue
                lines.append(line)
            return "\n".join(lines[:30])
        except Exception as e:
            log.error(f"OCR error: {e}")
            return ""

    # -- observe (store only on change) ----------------------------------------
    def observe(self):
        # Skip if paused or private window is active
        if self._paused or is_private_window():
            return
        img = self.capture()
        if img is None:
            return
        text = self.ocr(img)
        if not text or text == self._prev_text:
            return
        self._prev_text = text
        with self.lock:
            self.last_text = text
            self.history.append({
                "time": time.time(),
                "text": text,
            })
        preview = " | ".join(text.splitlines()[:3])
        log.info(f"Screen: {preview[:100]}")

    # -- history for chat context ----------------------------------------------
    def get_context(self, last_n: int = 10) -> str:
        with self.lock:
            entries = list(self.history)[-last_n:]
        if not entries:
            return "No screen observations yet."
        parts = []
        for e in entries:
            t = time.strftime("%H:%M:%S", time.localtime(e["time"]))
            preview = " | ".join(e["text"].splitlines()[:3])
            parts.append(f"[{t}] {preview}")
        return "\n".join(parts)

    # -- background loop -------------------------------------------------------
    def start(self):
        self._running = True
        def loop():
            # Wait for setup to complete before starting capture
            while self._running and not SETUP_COMPLETE:
                time.sleep(0.5)
            time.sleep(1)
            log.info(f"Screen reader started (every {CAPTURE_INTERVAL}s, monitor {SELECTED_MONITOR})")
            while self._running:
                self.observe()
                time.sleep(CAPTURE_INTERVAL)
        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def stop(self):
        self._running = False


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
CORS(app)
reader = ScreenReader()


@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Monitor API — list screens & get thumbnails
# ---------------------------------------------------------------------------
@app.route("/api/monitors")
def api_monitors():
    """List all available monitors with size info."""
    try:
        with mss.mss() as sct:
            monitors = []
            for i, m in enumerate(sct.monitors):
                label = "All Screens Combined" if i == 0 else f"Monitor {i}"
                monitors.append({
                    "index": i,
                    "label": label,
                    "width": m["width"],
                    "height": m["height"],
                    "left": m["left"],
                    "top": m["top"],
                })
        return jsonify({"monitors": monitors, "selected": SELECTED_MONITOR})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/monitors/preview/<int:idx>")
def api_monitor_preview(idx: int):
    """Capture a thumbnail preview of a specific monitor."""
    try:
        with mss.mss() as sct:
            if idx < 0 or idx >= len(sct.monitors):
                return jsonify({"error": "Invalid monitor index"}), 400
            monitor = sct.monitors[idx]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        # Resize to thumbnail (max 400px wide)
        w, h = img.size
        scale = min(400 / w, 300 / h, 1.0)
        thumb = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        thumb.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Setup / Onboarding API
# ---------------------------------------------------------------------------
@app.route("/api/setup/status")
def api_setup_status():
    """Return current setup state and system checks."""
    ollama_ok = False
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        ollama_ok = r.ok
    except Exception:
        pass

    return jsonify({
        "setup_complete": SETUP_COMPLETE,
        "tesseract_ok": TESSERACT_OK,
        "ollama_ok": ollama_ok,
        "selected_monitor": SELECTED_MONITOR,
        "llm_provider": LLM_PROVIDER,
    })


@app.route("/api/setup/complete", methods=["POST"])
def api_setup_complete():
    """Finalize setup with user choices."""
    global SETUP_COMPLETE, SELECTED_MONITOR, LLM_PROVIDER
    global OPENAI_API_KEY, OPENAI_MODEL, ANTHROPIC_API_KEY, ANTHROPIC_MODEL
    global CAPTURE_INTERVAL, PRIVACY_EXCLUDE

    body = request.get_json(force=True)

    if "monitor" in body:
        SELECTED_MONITOR = int(body["monitor"])
    if "llm_provider" in body:
        LLM_PROVIDER = body["llm_provider"]
    if "openai_key" in body and body["openai_key"]:
        OPENAI_API_KEY = body["openai_key"]
    if "openai_model" in body:
        OPENAI_MODEL = body["openai_model"]
    if "anthropic_key" in body and body["anthropic_key"]:
        ANTHROPIC_API_KEY = body["anthropic_key"]
    if "anthropic_model" in body:
        ANTHROPIC_MODEL = body["anthropic_model"]
    if "capture_interval" in body:
        CAPTURE_INTERVAL = max(1, int(body["capture_interval"]))
    if "privacy_exclude" in body:
        PRIVACY_EXCLUDE = [
            s.strip().lower()
            for s in body["privacy_exclude"]
            if s.strip()
        ]

    SETUP_COMPLETE = True
    log.info(f"Setup complete: monitor={SELECTED_MONITOR}, provider={LLM_PROVIDER}")
    return jsonify({"ok": True})


@app.route("/api/screen")
def api_screen():
    """Serve latest screenshot as PNG."""
    with reader.lock:
        data = reader.last_png
    if not data:
        return "", 204
    return send_file(io.BytesIO(data), mimetype="image/png")


@app.route("/api/history")
def api_history():
    """Return recent observations."""
    n = request.args.get("n", 15, type=int)
    with reader.lock:
        entries = list(reader.history)[-n:]
    result = []
    for e in entries:
        result.append({
            "time": time.strftime("%H:%M:%S", time.localtime(e["time"])),
            "text": e["text"],
        })
    return jsonify(result)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Chat with the LLM using screen context."""
    body = request.get_json(force=True)
    user_msg = body.get("message", "").strip()
    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    context = reader.get_context(last_n=12)
    current = reader.last_text or "Nothing captured yet."

    system_prompt = (
        "You are a helpful assistant that can see the user's screen. "
        "Below is what you've observed on their screen recently.\n\n"
        f"=== CURRENT SCREEN ===\n{current}\n\n"
        f"=== RECENT HISTORY ===\n{context}\n\n"
        "Answer the user's question based on what you see. "
        "Be concise and helpful. If you can't determine something from "
        "the screen content, say so."
    )

    try:
        answer = chat_llm(system_prompt, user_msg)
        return jsonify({"reply": answer})
    except requests.exceptions.ConnectionError:
        return jsonify({"reply": "Cannot reach LLM. Check your provider settings."}), 503
    except Exception as e:
        log.error(f"Chat error: {e}")
        return jsonify({"reply": f"Error: {e}"}), 500


@app.route("/api/status")
def api_status():
    """Quick health check."""
    with reader.lock:
        obs_count = len(reader.history)
    provider = LLM_PROVIDER.lower()
    llm_ok = False
    model_name = MODEL

    if provider == "openai" and OPENAI_API_KEY:
        llm_ok = True
        model_name = OPENAI_MODEL
    elif provider == "anthropic" and ANTHROPIC_API_KEY:
        llm_ok = True
        model_name = ANTHROPIC_MODEL
    else:
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            llm_ok = r.ok
        except Exception:
            pass

    return jsonify({
        "observations": obs_count,
        "llm": "connected" if llm_ok else "disconnected",
        "provider": provider,
        "model": model_name,
        "interval": CAPTURE_INTERVAL,
        "paused": reader._paused,
        "privacy_filters": PRIVACY_EXCLUDE,
        "setup_complete": SETUP_COMPLETE,
        "selected_monitor": SELECTED_MONITOR,
    })


@app.route("/api/pause", methods=["POST"])
def api_pause():
    """Toggle capture pause."""
    reader._paused = not reader._paused
    state = "paused" if reader._paused else "running"
    log.info(f"Screen reader {state}")
    return jsonify({"paused": reader._paused})


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Get or update runtime settings."""
    global LLM_PROVIDER, OPENAI_API_KEY, OPENAI_MODEL
    global ANTHROPIC_API_KEY, ANTHROPIC_MODEL, OLLAMA_URL, MODEL
    global CAPTURE_INTERVAL, PRIVACY_EXCLUDE, SELECTED_MONITOR

    if request.method == "GET":
        return jsonify({
            "llm_provider": LLM_PROVIDER,
            "ollama_url": OLLAMA_URL,
            "ollama_model": MODEL,
            "openai_model": OPENAI_MODEL,
            "openai_key_set": bool(OPENAI_API_KEY),
            "anthropic_model": ANTHROPIC_MODEL,
            "anthropic_key_set": bool(ANTHROPIC_API_KEY),
            "capture_interval": CAPTURE_INTERVAL,
            "privacy_exclude": PRIVACY_EXCLUDE,
            "selected_monitor": SELECTED_MONITOR,
        })

    body = request.get_json(force=True)
    if "llm_provider" in body:
        LLM_PROVIDER = body["llm_provider"]
    if "ollama_url" in body:
        OLLAMA_URL = body["ollama_url"]
    if "ollama_model" in body:
        MODEL = body["ollama_model"]
    if "openai_key" in body:
        OPENAI_API_KEY = body["openai_key"]
    if "openai_model" in body:
        OPENAI_MODEL = body["openai_model"]
    if "anthropic_key" in body:
        ANTHROPIC_API_KEY = body["anthropic_key"]
    if "anthropic_model" in body:
        ANTHROPIC_MODEL = body["anthropic_model"]
    if "capture_interval" in body:
        CAPTURE_INTERVAL = max(1, int(body["capture_interval"]))
    if "privacy_exclude" in body:
        PRIVACY_EXCLUDE = [
            s.strip().lower()
            for s in body["privacy_exclude"]
            if s.strip()
        ]
    if "selected_monitor" in body:
        SELECTED_MONITOR = int(body["selected_monitor"])
        log.info(f"Monitor changed to {SELECTED_MONITOR}")
    log.info(f"Settings updated: provider={LLM_PROVIDER}, monitor={SELECTED_MONITOR}")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # When running from PyInstaller bundle, set template folder
    if getattr(sys, "frozen", False):
        app.template_folder = _resource_path("templates")

    reader.start()
    url = f"http://localhost:{PORT}"
    log.info(f"Dashboard → {url}")
    log.info(f"LLM provider: {LLM_PROVIDER}")
    if PRIVACY_EXCLUDE:
        log.info(f"Privacy filters: {PRIVACY_EXCLUDE}")

    # Auto-open browser after a short delay
    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(url)
    threading.Thread(target=_open_browser, daemon=True).start()

    app.run(host="0.0.0.0", port=PORT, debug=False)
