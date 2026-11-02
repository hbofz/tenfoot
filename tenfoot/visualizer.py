"""Frequency bands of what the TV is playing, for the Spotify screen's visualizer."""
import subprocess

import numpy as np

BANDS = 48
RATE, FPS, WINDOW = 22050, 50, 1024  # short window + fast hops = bars on the beat


def band_edges(n=BANDS, rate=RATE, size=WINDOW, lo=40, hi=10000):
    """FFT bin boundaries for n log-spaced bands (how ears hear pitch), each at least 1 bin wide."""
    edges = np.round(np.geomspace(lo, hi, n + 1) * size / rate).astype(int)
    for i in range(1, len(edges)):
        edges[i] = max(edges[i], edges[i - 1] + 1)
    return edges


def band_levels(mag, edges):
    """Mean FFT magnitude inside each band, in one numpy call."""
    return np.add.reduceat(mag, edges)[:-1] / np.diff(edges)


def stream(write):
    """Read the HDMI output's monitor (playback is untouched) and write one line per frame: BANDS
    levels 0-99, bass to treble, with automatic gain so quiet and loud songs both fill the bars.
    Runs until write() fails."""
    source = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True).stdout.strip() + ".monitor"
    rec = subprocess.Popen(["parec", f"--device={source}", "--format=s16le", f"--rate={RATE}", "--channels=1",
                            "--latency-msec=10"], stdout=subprocess.PIPE)  # small buffer: the beat arrives on time
    edges, window, tilt = band_edges(), np.hanning(WINDOW), np.linspace(1, 3, BANDS)
    buf, hop, peak = np.zeros(WINDOW, np.float32), RATE // FPS, 1e-3
    try:
        while True:
            raw = rec.stdout.read(hop * 2)
            if not raw:
                break
            new = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
            buf = np.concatenate([buf[len(new):], new])
            mag = np.abs(np.fft.rfft(buf * window))
            bands = band_levels(mag, edges) * tilt  # treble is naturally quieter; lift it
            peak = max(peak * 0.995 ** (50 / FPS), bands.max(), 1e-3)  # gain follows the song, decays ~22%/s
            level = np.sqrt(np.clip(bands / peak, 0, 1))  # sqrt: small movements stay visible
            write(",".join(str(int(v * 99)) for v in level))
    finally:
        rec.kill()
        rec.wait()  # reap it, or every visit to the Spotify screen leaves a zombie
