"""A virtual keyboard and mouse (uinput): to the browser, the phone remote is a real keyboard and mouse."""
import threading

from evdev import AbsInfo, UInput, ecodes as e

KEYS = {  # remote button -> evdev key name
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "ok": "KEY_ENTER", "playpause": "KEY_PLAYPAUSE", "backspace": "KEY_BACKSPACE",
    "enter": "KEY_ENTER",  # the phone's typing sends this: OK while the cursor is on clicks instead
    "space": "KEY_SPACE",
}


class Input:
    def __init__(self, width, height):
        self.lock = threading.Lock()
        keys = [getattr(e, k) for k in set(KEYS.values()) | {"KEY_ESC", "KEY_LEFTALT"}]
        self.kbd = UInput({e.EV_KEY: keys}, name="tenfoot-keyboard")
        self.mouse = UInput({e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT], e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL]},
                            name="tenfoot-mouse")
        # The cursor puts the pointer at a spot on the screen (no pointer acceleration in the way).
        self.spot = UInput({e.EV_KEY: [e.BTN_LEFT], e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, width - 1, 0, 0, 0)),
                                                              (e.ABS_Y, AbsInfo(0, 0, height - 1, 0, 0, 0))]},
                           name="tenfoot-cursor")

    def point(self, x, y):
        with self.lock:
            self.spot.write(e.EV_ABS, e.ABS_X, int(x))
            self.spot.write(e.EV_ABS, e.ABS_Y, int(y))
            self.spot.syn()

    def press(self, names):
        """Press names in order, release in reverse (so ['KEY_LEFTALT','KEY_LEFT'] is a chord)."""
        codes = [getattr(e, n) for n in names]
        with self.lock:
            for c in codes:
                self.kbd.write(e.EV_KEY, c, 1)
            self.kbd.syn()  # separate frames, so nothing sees a zero-length press
            for c in reversed(codes):
                self.kbd.write(e.EV_KEY, c, 0)
            self.kbd.syn()

    def move(self, dx, dy):
        with self.lock:
            self.mouse.write(e.EV_REL, e.REL_X, round(dx))
            self.mouse.write(e.EV_REL, e.REL_Y, round(dy))
            self.mouse.syn()

    def click(self, button="left"):
        b = e.BTN_RIGHT if button == "right" else e.BTN_LEFT
        with self.lock:
            self.mouse.write(e.EV_KEY, b, 1)
            self.mouse.syn()
            self.mouse.write(e.EV_KEY, b, 0)
            self.mouse.syn()

    def scroll(self, notches):
        with self.lock:
            self.mouse.write(e.EV_REL, e.REL_WHEEL, int(notches))
            self.mouse.syn()
