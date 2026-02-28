# AI Cowork

An AI assistant that watches your screen in real-time and answers questions about what you're working on.

It captures your laptop screen via **mss**, reads text with **Tesseract OCR**, keeps an in-memory session history, and lets you chat with an LLM that knows what was on your screen.

**100% local by default** — your screen data never leaves your machine.

![Dashboard](https://img.shields.io/badge/dashboard-localhost:8080-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![License](https://img.shields.io/badge/license-MIT-gray)

## Features

- **Live screen capture** with OCR text extraction
- **Chat with your screen** — ask questions about what you see
- **Multiple LLM backends** — Ollama (local), OpenAI, Anthropic Claude
- **Privacy filter** — exclude windows by title (banking, passwords, etc.)
- **Pause/resume** capture from the dashboard
- **Settings UI** — switch providers, set API keys, adjust capture interval
- **In-memory only** — nothing is saved to disk

## How It Works

1. **Screen Capture** — Takes a screenshot every 5 seconds using `mss`
2. **OCR** — Extracts text from the screenshot using Tesseract
3. **History** — Stores observations in memory (session only)
4. **Chat** — Send a question via the dashboard; the LLM answers using screen context

## Quick Start

### Option A: Download (Windows)

1. Download the latest release from [Releases](https://github.com/SamiFdal/ai-cowork/releases)
2. Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
3. Run `ai-cowork.exe`
4. Open http://localhost:8080

### Option B: From source

```bash
# 1. Clone
git clone https://github.com/SamiFdal/ai-cowork.git
cd ai-cowork

# 2. Copy config
cp .env.example .env
# Edit .env — set your TESSERACT_PATH

# 3. Install Python deps
pip install -r requirements.txt

# 4. Start Ollama (optional — for local LLM)
docker compose up -d

# 5. Run
python app.py
```

Open **http://localhost:8080** — you'll see a live screen preview and chat panel.

On Windows, you can also double-click `start.bat`.

## LLM Providers

| Provider | Setup | GPU Required |
|----------|-------|-------------|
| **Ollama** (default) | `docker compose up -d` | Yes (NVIDIA) |
| **OpenAI** | Set API key in Settings | No |
| **Anthropic** | Set API key in Settings | No |

Switch providers anytime from the Settings panel in the dashboard — no restart needed.

## Privacy

- **Privacy filter**: Exclude windows containing specific keywords (e.g., `banking, 1password, keepass`). Set in Settings or `.env`.
- **Pause button**: Instantly stop all screen capture.
- **No persistence**: Nothing is saved to disk. History is lost when you close the app.
- **Fully local**: With Ollama, zero data leaves your machine.

## Project Structure

```
.env.example        # Config template
app.py              # Main app (screen reader + Flask + chat)
docker-compose.yml  # Ollama with GPU
requirements.txt    # Python dependencies
start.bat           # Windows launcher
templates/
  index.html        # Dashboard UI
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | `ollama`, `openai`, or `anthropic` |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `REASONING_MODEL` | `qwen2.5:7b` | Ollama model name |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Claude model |
| `CAPTURE_INTERVAL` | `5` | Seconds between screen captures |
| `HISTORY_SIZE` | `50` | Max observations kept in memory |
| `DASHBOARD_PORT` | `8080` | Web dashboard port |
| `PRIVACY_EXCLUDE` | — | Comma-separated window title keywords to exclude |
| `TESSERACT_PATH` | auto-detected | Path to tesseract.exe |

## Building the .exe

```bash
pip install pyinstaller
pyinstaller ai-cowork.spec
```

The output will be in `dist/ai-cowork/`.

## License

MIT
