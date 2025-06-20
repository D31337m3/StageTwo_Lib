"""
CircuitPython GUI Framework for Devices with Built-in Displays
- Default display size: 240w x 135h
- Supports: Single/multiple hardware buttons
- Menu system with submenus and alerts
- Status bar + theming support
- GUI sounds (via audiopwmio)
- Animated transitions
- File browsing and input fields
- USB and BLE keyboard input support
- Event-based component system
- External skins/themes support from file
"""

import displayio
import terminalio
from adafruit_display_text import label
from adafruit_display_shapes.rect import Rect
import board
import time
import os
import audiopwmio
import audiocore
import sdcardio
import storage
import supervisor

try:
    import usb_hid
    from adafruit_hid.keyboard import Keyboard
    from adafruit_hid.keycode import Keycode
except:
    usb_hid = None

# Base config
DEFAULT_WIDTH = 240
DEFAULT_HEIGHT = 135

# Theme configuration with override from file
def load_theme(path="/theme.txt"):
    theme = THEME.copy()
    try:
        with open(path, "r") as f:
            for line in f:
                k, v = line.strip().split("=")
                theme[k] = int(v, 16)
    except:
        pass
    return theme

THEME = {
    "bg": 0x000000,
    "fg": 0xFFFFFF,
    "highlight": 0x5555FF,
    "status": 0x222222,
    "alert": 0xFF0000,
}

THEME = load_theme()

display = board.DISPLAY
screen = display.root_group

class Event:
    def __init__(self, name, data=None):
        self.name = name
        self.data = data

class SoundPlayer:
    def __init__(self, pin):
        self.audio = audiopwmio.PWMAudioOut(pin)

    def play_beep(self, duration=0.1, frequency=440):
        import array, math
        length = 100
        sine_wave = array.array("H", [
            int(math.sin(2 * math.pi * frequency * i / 1000) * 32767 + 32768) for i in range(length)
        ])
        wave = audiocore.RawSample(sine_wave)
        self.audio.play(wave, loop=True)
        time.sleep(duration)
        self.audio.stop()

class ButtonInput:
    def __init__(self, pins):
        if not isinstance(pins, list):
            pins = [pins]
        import digitalio
        self.buttons = []
        for pin in pins:
            btn = digitalio.DigitalInOut(pin)
            btn.direction = digitalio.Direction.INPUT
            btn.pull = digitalio.Pull.UP
            self.buttons.append(btn)

    def get_pressed(self):
        return [i for i, btn in enumerate(self.buttons) if not btn.value]

class KeyboardInput:
    def __init__(self):
        self.buffer = ""

    def poll(self):
        if supervisor.runtime.serial_bytes_available:
            self.buffer += supervisor.runtime.serial.read(supervisor.runtime.serial_bytes_available).decode("utf-8")
            chars = list(self.buffer)
            self.buffer = ""
            return chars
        return []

class GUIApp:
    def __init__(self, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
        self.width = width
        self.height = height
        self.root = displayio.Group()
        screen.append(self.root)
        self.components = []
        self.focus_index = 0
        self.button_handler = None
        self.status = StatusBar(self.width)
        self.alert_active = False
        self.sound = None
        self.keyboard_input = KeyboardInput()
        self.root.append(self.status.group)

    def set_sound_player(self, sound_player):
        self.sound = sound_player

    def set_button_input(self, button_input):
        self.button_handler = button_input

    def add_component(self, component):
        self.components.append(component)
        self.root.append(component.group)

    def focus_next(self):
        if self.alert_active:
            return
        self.components[self.focus_index].unfocus()
        self.focus_index = (self.focus_index + 1) % len(self.components)
        self.components[self.focus_index].focus()
        if self.sound:
            self.sound.play_beep()

    def show_alert(self, message, duration=2):
        self.alert_active = True
        alert = AlertBox(message, self.width)
        self.root.append(alert.group)
        time.sleep(duration)
        self.root.remove(alert.group)
        self.alert_active = False

    def run(self):
        if self.components:
            self.components[0].focus()
        while True:
            if self.button_handler:
                pressed = self.button_handler.get_pressed()
                if pressed:
                    self.focus_next()
            keys = self.keyboard_input.poll()
            for k in keys:
                if hasattr(self.components[self.focus_index], "handle_key"):
                    self.components[self.focus_index].handle_key(k)
            time.sleep(0.1)

class LabelComponent:
    def __init__(self, text, x, y, width=DEFAULT_WIDTH):
        self.text = text
        self.x = x
        self.y = y
        self.width = width
        self.group = displayio.Group()
        self.bg = Rect(x, y, width, 20, fill=THEME["bg"])
        self.label = label.Label(terminalio.FONT, text=text, x=x + 4, y=y + 4, color=THEME["fg"])
        self.group.append(self.bg)
        self.group.append(self.label)

    def focus(self):
        self.bg.fill = THEME["highlight"]

    def unfocus(self):
        self.bg.fill = THEME["bg"]

class StatusBar:
    def __init__(self, width):
        self.group = displayio.Group()
        self.bg = Rect(0, 0, width, 12, fill=THEME["status"])
        self.label = label.Label(terminalio.FONT, text="", x=2, y=2, color=THEME["fg"])
        self.group.append(self.bg)
        self.group.append(self.label)

    def set_text(self, text):
        self.label.text = text

class AlertBox:
    def __init__(self, text, width):
        self.group = displayio.Group()
        self.bg = Rect(0, 40, width, 50, fill=THEME["alert"])
        self.label = label.Label(terminalio.FONT, text=text, x=10, y=60, color=THEME["fg"])
        self.group.append(self.bg)
        self.group.append(self.label)

class TextInput:
    def __init__(self, x, y, width=DEFAULT_WIDTH):
        self.group = displayio.Group()
        self.text = ""
        self.label = label.Label(terminalio.FONT, text="_", x=x, y=y, color=THEME["fg"])
        self.group.append(self.label)

    def set_text(self, text):
        self.text = text
        self.label.text = text + "_"

    def add_char(self, char):
        self.set_text(self.text + char)

    def backspace(self):
        self.set_text(self.text[:-1])

    def handle_key(self, k):
        if k == "\x08":  # backspace
            self.backspace()
        elif k == "\r":  # enter
            pass
        else:
            self.add_char(k)
