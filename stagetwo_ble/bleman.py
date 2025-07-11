import board
import displayio
from adafruit_display_text import label
import terminalio
import time
import digitalio

from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.advertising import Advertisement
from adafruit_ble.services.standard.device_info import DeviceInfoService

# ========== CONFIG ==========
BUTTON_PIN = board.BUTTON  # Should be correct for esp32-s3-geek
EXIT_TO_APP = "app_loader.py"
CONTEXT_MENU_ENABLED = True

# ========== BUTTON HANDLING ==========
class ButtonHandler:
    def __init__(self, pin):
        self.button = digitalio.DigitalInOut(pin)
        self.button.switch_to_input(pull=digitalio.Pull.UP)
        self.last_state = True
        self.last_time = 0
        self.click_count = 0
        self.long_press = False
        self.very_long_press = False
        self.last_up_time = 0

    def update(self):
        state = self.button.value
        now = time.monotonic()
        events = []

        # Button pressed
        if not state and self.last_state:
            self.last_time = now
            self.long_press = False
            self.very_long_press = False

        # Button held
        if not state:
            duration = now - self.last_time
            if duration > 5 and not self.very_long_press:
                events.append("very_long_press")
                self.very_long_press = True
            elif duration > 1.0 and not self.long_press:
                events.append("long_press")
                self.long_press = True

        # Button released
        if state and not self.last_state:
            duration = now - self.last_time
            if duration < 0.3:
                self.click_count += 1
                self.last_up_time = now
            elif 1.0 > duration >= 0.3:
                events.append("short_press")
            self.long_press = False
            self.very_long_press = False

        # Double click detection
        if self.click_count == 1 and (now - self.last_up_time) > 0.4:
            events.append("single_click")
            self.click_count = 0
        if self.click_count == 2:
            events.append("double_click")
            self.click_count = 0

        self.last_state = state
        return events

# ========== GUI ==========
class BluetoothGUI:
    def __init__(self, display, root_group_name="root_group"):
        self.display = display
        self.root_group = displayio.Group()
        setattr(display, root_group_name, self.root_group)
        self.title = label.Label(terminalio.FONT, text="BLE Manager", color=0xFFFFFF, x=5, y=5)
        self.instructions = label.Label(terminalio.FONT, text="Click to scan...", color=0xAAAAAA, x=5, y=25)
        self.device_labels = []
        self.selected_idx = 0
        self.devices = []
        self.status = label.Label(terminalio.FONT, text="", color=0x00FF00, x=5, y=display.height-15)
        self.root_group.append(self.title)
        self.root_group.append(self.instructions)
        self.root_group.append(self.status)

    def update_devices(self, devices):
        # Remove old device labels
        for lbl in self.device_labels:
            self.root_group.remove(lbl)
        self.device_labels = []
        self.devices = devices
        # Add device labels
        y = 45
        for idx, dev in enumerate(devices):
            color = 0xFFFF00 if idx == self.selected_idx else 0xFFFFFF
            name = getattr(dev, "complete_name", None) or \
                   getattr(dev, "short_name", None) or \
                   str(getattr(dev, "address", "Unknown"))
            lbl = label.Label(terminalio.FONT, text=f"{idx+1}. {name}", color=color, x=5, y=y)
            self.device_labels.append(lbl)
            self.root_group.append(lbl)
            y += 15

    def set_status(self, text, color=0x00FF00):
        self.status.text = text
        self.status.color = color

    def move_selection(self, step):
        self.selected_idx = (self.selected_idx + step) % len(self.devices) if self.devices else 0
        self.update_devices(self.devices)

    def show_context_menu(self):
        self.set_status("Context menu: Info/Pair", color=0xFF8800)

    def clear_context_menu(self):
        self.set_status("")

    def show_message(self, msg, color=0x00FF00):
        self.set_status(msg, color=color)

# ========== MAIN APP ==========
def main():
    ble = BLERadio()
    display = board.DISPLAY
    gui = BluetoothGUI(display)
    button = ButtonHandler(BUTTON_PIN)

    app_state = "idle"
    found_devices = []
    current_device = None

    gui.show_message("Click to scan", color=0x00FF00)

    while True:
        events = button.update()

        # Button events
        for event in events:
            if event == "very_long_press":
                gui.show_message("Exiting...", color=0xFF0000)
                time.sleep(0.5)
                import supervisor
                supervisor.set_next_code_file(EXIT_TO_APP)
                supervisor.reload()
            elif event == "single_click":
                if app_state == "idle":
                    gui.show_message("Scanning...", color=0x00FFFF)
                    found_devices = []
                    for adv in ble.start_scan(timeout=5, minimum_rssi=-80):
                        if isinstance(adv, Advertisement) and adv not in found_devices:
                            found_devices.append(adv)
                    ble.stop_scan()
                    gui.update_devices(found_devices)
                    app_state = "list"
                    gui.show_message("Scan done. Click to navigate.", color=0x00FF00)
                elif app_state == "list":
                    gui.move_selection(1)
                elif app_state == "context":
                    gui.clear_context_menu()
                    app_state = "list"
            elif event == "long_press":
                if app_state == "list" and found_devices:
                    adv = found_devices[gui.selected_idx]
                    gui.show_message("Pairing...", color=0xFFFF00)
                    try:
                        connection = ble.connect(adv)
                        if DeviceInfoService in connection:
                            devinfo = connection[DeviceInfoService]
                            gui.show_message(f"Paired: {devinfo.manufacturer}")
                        else:
                            gui.show_message("Paired!", color=0x00FF00)
                        connection.disconnect()
                    except Exception as e:
                        gui.show_message(f"Failed: {e}", color=0xFF0000)
            elif event == "double_click":
                if app_state == "list" and CONTEXT_MENU_ENABLED:
                    gui.show_context_menu()
                    app_state = "context"

        time.sleep(0.05)

if __name__ == "__main__":
    main()