# Luminary

A local-first media player and library for Windows 11. Built with PyQt6 and LibVLC for native hardware-accelerated playback of 10-bit HEVC, MKV, FLAC, and styled subtitles directly in-window.

## Features

- **Embedded Player**: Direct LibVLC playback with audio track and subtitle switching.
- **Auto-Scan & Metadata**: Scrapes series and movie metadata without requiring API keys.
- **Watch Tracking**: Automatic resume positions, progress indicators, and watch history.
- **Tactile UI**: Modern dark theme with smooth micro-interactions.

## Usage

```powershell
pip install -r requirements.txt
python main.py
```

Or double-click `run_luminary.bat`.

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- [VLC Media Player](https://www.videolan.org/vlc/) (64-bit)
