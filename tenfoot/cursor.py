"""A pointer driven by the remote's arrows, for anything the highlight can't reach. An arrow tap
nudges it; held, it glides, picking up speed; OK clicks; pushing past the top or bottom scrolls.
inject/pointer.js gives it a picture big enough to see from the couch."""
import threading
import time

DIRS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
NUDGE = 20  # px, a tap


def glide_speed(t):
    """Pixels a second once an arrow has been held t seconds: none in the first 0.15 s (a tap's
    nudge is all), then from 300 (aiming at a small button) up to 2000 (across the screen in a second)."""
    return 0 if t < 0.15 else min(2000, 300 + 2400 * (t - 0.15))


class Cursor:
    def __init__(self, inp, width, height, toast=lambda text, ms: None, keyboard_open=lambda: False):
        self.inp, self.w, self.h = inp, width, height
        self.toast = toast
        self.keyboard_open = keyboard_open
        self.on = False
        self.x, self.y = width // 2, height // 2
        self.held = {}
        self.timer = self.glider = None
        self.wheel = 0

    def to(self, dx, dy):
        """Move by dx, dy, stopping at the screen's edges. Pushing on past the top or bottom scrolls
        the page instead, 10 notches a second at most."""
        x, y = self.x + dx, self.y + dy
        if (y < 0 or y > self.h - 1) and time.time() - self.wheel > 0.1:
            self.wheel = time.time()
            self.inp.scroll(1 if y < 0 else -1)
        self.x, self.y = min(self.w - 1, max(0, x)), min(self.h - 1, max(0, y))
        self.inp.point(self.x, self.y)

    def glide(self, k, down):
        """A physical remote's arrow: a press nudges at once and, until the release, it glides 60
        steps a second (the remote's own repeats come 30 a second, in jumps)."""
        if not down:
            self.held.pop(k, None)
            return
        self.held[k] = time.time()
        self._alive()
        self.to(NUDGE * DIRS[k][0], NUDGE * DIRS[k][1])
        if not (self.glider and self.glider.is_alive()):
            self.glider = threading.Thread(target=self._gliding, daemon=True)
            self.glider.start()

    def _gliding(self):
        last = time.time()
        while self.held and self.on:
            time.sleep(1 / 60)
            now = time.time()
            dt, last = now - last, now
            dx = dy = 0.0
            for k, t0 in list(self.held.items()):
                if now - t0 > 10:  # its release never came (the remote dropped out mid-press)
                    self.held.pop(k, None)
                    continue
                v = glide_speed(now - t0) * dt
                dx, dy = dx + DIRS[k][0] * v, dy + DIRS[k][1] * v
            if dx or dy:
                self.to(dx, dy)

    def set(self, on, quiet=False):
        """On (mid-screen, where it's easy to find) or away (the bottom right corner). Quietly: it just
        stops taking keys where it is; inject/pointer.js hides its picture once it rests."""
        self.on, self.x, self.y = on, self.w // 2, self.h // 2
        self.held.clear()
        if self.timer:
            self.timer.cancel()
        if on:
            self._alive()
            self.inp.point(self.x, self.y)
        elif quiet:
            return
        else:
            self.inp.point(self.w - 1, self.h - 1)
        self.toast("Cursor: arrows move it, OK clicks. Press again to stop" if on else "Cursor off", 4000 if on else 1200)

    def _alive(self):
        """A minute without a key and it goes away (the next person expects the arrows to move the highlight)."""
        if self.timer:
            self.timer.cancel()
        self.timer = threading.Timer(60, self.set, (False, True))
        self.timer.daemon = True
        self.timer.start()

    def key(self, cmd):
        """A key while the cursor is on: True if the cursor took it."""
        a, k = cmd.get("a"), cmd.get("k")
        if a == "key" and k in DIRS:
            self.to(NUDGE * DIRS[k][0], NUDGE * DIRS[k][1])
        elif a == "key" and k == "ok":
            self.inp.click()
            threading.Thread(target=self._typing_after_click, daemon=True).start()
        elif a in ("back", "home"):
            self.set(False)
            return a == "back"  # Back only puts the cursor away; Home goes home too
        else:
            return False
        self._alive()
        return True

    def _typing_after_click(self):
        """A click that put the text cursor in a box opens the TV's keyboard: the arrows and OK are the keyboard's then."""
        time.sleep(0.2)
        try:
            if self.on and self.keyboard_open():
                self.set(False, quiet=True)
        except Exception:
            pass  # no page to ask: the cursor stays
