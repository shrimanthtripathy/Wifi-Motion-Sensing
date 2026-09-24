"""
WiFi Sensing — standalone
A single script that reads your laptop's WiFi signal strength, computes a
rolling motion score and a short-time FFT ("spectral waveform"), and shows
everything in a live matplotlib window. No browser, no server — just run
this file directly.

Run:  python wifi_sensing.py

Dependencies: numpy, matplotlib
Install with: pip install numpy matplotlib --break-system-packages
"""

import platform
import re
import subprocess
import time
from collections import deque

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# ---------------- Configuration ----------------
SAMPLE_INTERVAL_MS = 250     # milliseconds between samples (~4 Hz)
HISTORY_SECONDS = 30          # how much history to show on the line charts
BUFFER_LEN = int(HISTORY_SECONDS * 1000 / SAMPLE_INTERVAL_MS)
MOTION_WINDOW = 8             # samples used for the rolling std "motion score"
MOTION_THRESHOLD = 1.5        # tune this after watching a few minutes live
FFT_WINDOW_SAMPLES = 64       # how many recent samples feed each FFT column
SPECTROGRAM_WIDTH = 120       # how many FFT columns to show side by side

OS_NAME = platform.system()   # 'Windows', 'Darwin' (mac), or 'Linux'

_last_error_printed = None    # avoid spamming the same error every tick


def _log_once(msg):
    global _last_error_printed
    if msg != _last_error_printed:
        print(f"[wifi-sensing] {msg}")
        _last_error_printed = msg


def get_rssi():
    """
    Return current WiFi signal strength as a float, or None if unavailable.
    - Windows: signal quality as a percent (0-100)
    - macOS / Linux: RSSI in dBm (typically -30 to -90)
    The absolute scale doesn't matter for motion detection — only the
    fluctuations over time do. Failures are logged (throttled) so problems
    are visible in the terminal instead of just producing a flat line.
    """
    try:
        if OS_NAME == "Windows":
            # Primary: query the actual dBm RSSI via WMI. This has much finer
            # resolution than netsh's rounded 0-100% "quality" score, which
            # barely moves unless the change is large.
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance -Namespace root\\wmi -ClassName "
                     "MSNdis_80211_ReceivedSignalStrength -ErrorAction Stop)."
                     "Ndis80211ReceivedSignalStrength"],
                    stderr=subprocess.DEVNULL, text=True, timeout=3,
                ).strip()
                if out:
                    return float(out.splitlines()[0])
            except Exception:
                pass  # fall through to netsh below

            out = subprocess.check_output(
                ["netsh", "wlan", "show", "interfaces"],
                stderr=subprocess.DEVNULL, text=True, timeout=2,
            )
            m = re.search(r"Signal\s*:\s*(\d+)%", out)
            if not m:
                _log_once(
                    "Couldn't find 'Signal' in 'netsh wlan show interfaces' output. "
                    "Raw output was:\n" + out[:500]
                )
                return None
            _log_once(
                "Using netsh's rounded signal % (WMI dBm query unavailable on this "
                "machine) — motion sensitivity will be coarser."
            )
            return float(m.group(1))

        elif OS_NAME == "Darwin":  # macOS
            airport = (
                "/System/Library/PrivateFrameworks/Apple80211.framework/"
                "Versions/Current/Resources/airport"
            )
            try:
                out = subprocess.check_output(
                    [airport, "-I"], stderr=subprocess.DEVNULL, text=True, timeout=2,
                )
            except FileNotFoundError:
                _log_once(
                    "The 'airport' utility isn't present on this Mac (removed on "
                    "macOS Sonoma and later). Tell Claude your macOS version for a fix."
                )
                return None
            m = re.search(r"agrCtlRSSI:\s*(-?\d+)", out)
            if not m:
                _log_once(
                    "Couldn't find 'agrCtlRSSI' — Terminal may need Location Services "
                    "permission (System Settings > Privacy & Security > Location "
                    "Services). Raw output was:\n" + out[:500]
                )
                return None
            return float(m.group(1))

        elif OS_NAME == "Linux":
            out = subprocess.check_output(
                ["nmcli", "-t", "-f", "active,signal", "dev", "wifi"],
                stderr=subprocess.DEVNULL, text=True, timeout=2,
            )
            for line in out.splitlines():
                if line.startswith("yes:"):
                    return float(line.split(":")[1])
            _log_once(
                "No WiFi interface marked 'active' in nmcli output. Raw output was:\n"
                + out[:500]
            )
            return None
    except FileNotFoundError as e:
        _log_once(f"Command not found ({e}). Is the required network tool installed?")
        return None
    except Exception as e:
        _log_once(f"Unexpected error reading signal: {e!r}")
        return None
    return None


def compute_spectrum(values, n_points=FFT_WINDOW_SAMPLES):
    """Short-time FFT over the most recent samples -> normalized magnitude bins."""
    arr = np.array(values[-n_points:], dtype=float)
    if len(arr) < 8:
        return np.zeros(n_points // 2 + 1)
    if len(arr) < n_points:
        arr = np.pad(arr, (n_points - len(arr), 0), mode="edge")
    arr = arr - np.mean(arr)
    window = np.hanning(len(arr))
    fft_vals = np.fft.rfft(arr * window)
    mags = np.abs(fft_vals)
    if mags.max() > 0:
        mags = mags / mags.max()
    return mags


# ---------------- State ----------------
rssi_buffer = deque(maxlen=BUFFER_LEN)
motion_buffer = deque(maxlen=BUFFER_LEN)
spectrogram = np.zeros((FFT_WINDOW_SAMPLES // 2 + 1, SPECTROGRAM_WIDTH))

# ---------------- Plot setup ----------------
plt.style.use("dark_background")
fig, (ax_rssi, ax_motion, ax_spec, ax_thermal) = plt.subplots(
    4, 1, figsize=(9, 10), gridspec_kw={"height_ratios": [1, 1, 1.3, 0.6]}
)
fig.suptitle("WiFi motion sensing (live)", fontsize=13)
fig.canvas.manager.set_window_title("WiFi motion sensing")

(line_rssi,) = ax_rssi.plot([], [], color="#4da3ff", linewidth=1.5)
ax_rssi.set_title("Signal strength", fontsize=10, loc="left")
ax_rssi.set_xlim(0, BUFFER_LEN)

(line_motion,) = ax_motion.plot([], [], color="#ff9f4d", linewidth=1.5)
ax_motion.axhline(MOTION_THRESHOLD, color="#888", linestyle="--", linewidth=1)
ax_motion.set_title("Motion score (rolling std)", fontsize=10, loc="left")
ax_motion.set_xlim(0, BUFFER_LEN)

im_spec = ax_spec.imshow(
    spectrogram, aspect="auto", origin="lower", cmap="magma",
    vmin=0, vmax=1, interpolation="nearest",
)
ax_spec.set_title("Spectral waveform (scrolling spectrogram)", fontsize=10, loc="left")
ax_spec.set_xlabel("time \u2192")
ax_spec.set_ylabel("frequency bin")

thermal_data = np.zeros((1, 1))
im_thermal = ax_thermal.imshow(
    thermal_data, aspect="auto", cmap="inferno", vmin=0, vmax=1,
    extent=[0, 1, 0, 1],
)
ax_thermal.set_title(
    "Motion intensity (thermal-style — reflects amount of motion, not location)",
    fontsize=10, loc="left",
)
ax_thermal.set_xticks([])
ax_thermal.set_yticks([])

status_text = fig.text(0.02, 0.97, "Waiting for data...", fontsize=11, color="#8fa")

fig.tight_layout(rect=[0, 0, 1, 0.94])


def update(_frame):
    val = get_rssi()
    if val is not None:
        rssi_buffer.append(val)

    values = list(rssi_buffer)
    motion_score = None
    if len(values) >= MOTION_WINDOW:
        motion_score = float(np.std(values[-MOTION_WINDOW:]))
        motion_buffer.append(motion_score)

    # RSSI line
    if values:
        line_rssi.set_data(range(len(values)), values)
        ax_rssi.set_xlim(0, max(BUFFER_LEN, len(values)))
        pad = 2
        ax_rssi.set_ylim(min(values) - pad, max(values) + pad)

    # Motion score line
    mvals = list(motion_buffer)
    if mvals:
        line_motion.set_data(range(len(mvals)), mvals)
        ax_motion.set_xlim(0, max(BUFFER_LEN, len(mvals)))
        top = max(mvals + [MOTION_THRESHOLD]) + 0.5
        ax_motion.set_ylim(0, top)

    # Spectrogram: shift left, insert new column
    if len(values) >= 16:
        spectrum = compute_spectrum(values)
        spectrogram[:, :-1] = spectrogram[:, 1:]
        spectrogram[:, -1] = spectrum
        im_spec.set_data(spectrogram)

    # Thermal-style motion intensity panel: whole-frame color intensity
    # reflects how much motion is currently happening (not where it is —
    # a single WiFi link can't localize within the room, only sense that
    # something moved). A little texture noise is added purely so it reads
    # as a "heat" field rather than a flat color swatch.
    if motion_score is not None:
        intensity = np.clip(motion_score / (MOTION_THRESHOLD * 2.5), 0, 1)
    else:
        intensity = 0.0
    grid = np.full((20, 40), intensity) + np.random.normal(0, 0.03, (20, 40))
    grid = np.clip(grid, 0, 1)
    im_thermal.set_data(grid)

    # Status text
    if val is None:
        status_text.set_text("No signal reading — check terminal for details")
        status_text.set_color("#e06666")
    elif motion_score is not None and motion_score > MOTION_THRESHOLD:
        status_text.set_text(f"Motion detected  (score {motion_score:.2f})")
        status_text.set_color("#ffb066")
    else:
        score_str = f"{motion_score:.2f}" if motion_score is not None else "..."
        status_text.set_text(f"No motion  (score {score_str})")
        status_text.set_color("#8fdca0")

    return line_rssi, line_motion, im_spec, im_thermal, status_text


if __name__ == "__main__":
    print(f"[wifi-sensing] Detected OS: {OS_NAME}")
    print("[wifi-sensing] Running a one-time signal check...")
    test_val = get_rssi()
    if test_val is None:
        print(
            "[wifi-sensing] WARNING: couldn't read WiFi signal strength (see any "
            "details above). The plot window will open but stay flat until this "
            "is fixed — it keeps retrying every 0.25s."
        )
    else:
        print(f"[wifi-sensing] Signal check OK: {test_val}")

    ani = FuncAnimation(fig, update, interval=SAMPLE_INTERVAL_MS, blit=False)
    plt.show()
