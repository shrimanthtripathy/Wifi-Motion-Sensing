# WiFi Motion Sensing

Device-free motion detection using nothing but a home Wi-Fi router and an
unmodified laptop — no extra hardware, no monitor mode, no admin rights.
Movement disturbs the multipath reflections of the WiFi signal, which shows
up as small fluctuations in signal strength (RSSI). This project samples
those fluctuations, scores them for motion, and visualizes both a spectral
waveform and a thermal-style motion-intensity view, live.

## Contents

- **`wifi_sensing.py`** — the main deliverable. A single standalone Python
  script with its own live `matplotlib` visualization window (RSSI trace,
  motion score, scrolling spectrogram, thermal intensity panel). No browser,
  no server.
- **`web-dashboard/`** — an earlier browser-based version (Flask + WebSocket
  backend, HTML/JS dashboard). Kept for reference; the standalone script is
  the recommended way to run this.
- **`paper/research_paper.tex`** — an APA-formatted research report on the
  system's design, related work, and limitations, ready to open directly in
  Overleaf.

## Quick start

```bash
pip install -r requirements.txt
python wifi_sensing.py
```

A window opens showing live signal strength, a motion score against a
tunable threshold, a scrolling spectral waveform, and a thermal-style motion
intensity panel. Works on Windows, macOS, and Linux — it auto-detects the OS
and uses the right native command to read WiFi signal strength.

## How it works

1. Poll WiFi signal strength ~4 times/second via the OS's own tools
   (WMI/`netsh` on Windows, `airport` on macOS, `nmcli` on Linux).
2. Compute a rolling standard deviation over the last few samples as a
   **motion score** — a stable signal means stillness, a jumpy signal means
   movement.
3. Run a short-time FFT over the recent buffer to get a **spectral
   waveform** of the motion dynamics.
4. Render all of it live: RSSI trace, motion score, spectrogram, and a
   thermal-style intensity panel.

See `paper/research_paper.tex` for the full methodology, related work, and
an honest discussion of what single-link RSSI sensing can and can't do
(short version: great for "is something moving," not capable of pinpointing
*where* in the room without multiple sensing links).

## Limitations

- Windows' signal reporting can be coarse; the script tries a higher-
  resolution WMI query first and falls back to `netsh`'s rounded percentage
  if that's unavailable on your machine.
- This detects *that* motion is happening, not *where* — spatial
  localization needs 2–3 simultaneous sensing points, not one router/laptop
  pair. See the paper's "Future Work" section for the extension path
  (multi-node trilateration, or ESP32-based CSI for finer-grained sensing).

## License

MIT — see [LICENSE](LICENSE).
