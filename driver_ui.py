"""FSAE dashboard based on last year's Tkinter version.

Run without a port to try the dashboard with fake readings.
Use --port to read actual UART data from the STM32.
"""

import argparse
import math
import time
import tkinter as tk
from telemetry import Telemetry, Lines, MODES


# Keeping the colors here makes it easier to change the theme later.
BG = '#090d12'
PANEL = '#151d27'
WHITE = '#f3f6fa'
MUTED = '#aebdcd'
GREEN = '#60e6a6'
RED = '#ff7272'


class Dashboard:
    def __init__(self, root, args):
        self.root, self.args = root, args

        # The readings and UART message buffer are handled separately
        # from the code that draws the screen.
        self.data = Telemetry(args.stale)
        self.lines = Lines()

        # Leave the port disconnected until receive() tries to open it.
        self.serial = None
        self.retry_at = 0

        # Use elapsed time so changes to the system clock don't affect timing.
        self.started = time.monotonic()

        # These are only used to calculate average power in the demo.
        self.energy = self.duration = 0.0
        self.last_sim = self.started

        self.connection = 'SIMULATION' if not args.port else 'CONNECTING'

        # Counts messages that couldn't be accepted by the telemetry parser.
        self.bad_frames = 0

        root.title('FSAE Driver Dashboard')
        root.geometry('1000x600')
        root.minsize(480, 300)
        root.configure(bg=BG)
        root.attributes('-fullscreen', args.fullscreen)

        # Escape leaves fullscreen, and F11 switches it on or off.
        root.bind('<Escape>', lambda e: root.attributes('-fullscreen', False))
        root.bind('<F11>', self.toggle_fullscreen)
        root.protocol('WM_DELETE_WINDOW', self.close)

        # Everything is drawn on one canvas that grows with the window.
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)

        self.tick()

    def toggle_fullscreen(self, event=None):
        self.root.attributes(
            '-fullscreen',
            not self.root.attributes('-fullscreen')
        )

    def receive(self, now):
        # No port means we're testing the layout without any hardware.
        if not self.args.port:
            t = now - self.started

            # Make the demo power rise and fall so the display isn't static.
            watts = 22000 + 18000 * math.sin(t * .65)

            # Average demo power since the app started.
            # With real hardware, avg_pwr comes from the STM32 instead.
            dt = now - self.last_sim
            self.energy += watts * dt
            self.duration += dt
            self.last_sim = now
            average = self.energy / self.duration if self.duration else watts

            # Send fake readings through the same parser as the real data.
            self.data.feed(
                f'pwr={watts},avg_pwr={average},mode=1,tc=2,regen=1,'
                'draw_limit=60000,status=1,ts_active=1,fault_bms=0,'
                'fault_imd=0,fault_bspd=0,acc_v=350,min_v=3.7,max_v=3.9,'
                f'acc_t=32,mtr_t=55,cnt_t=44,cool_t=30,speed={45+20*math.sin(t)},'
                'gas=40,brk=0',
                now
            )
            return

        if self.serial is None:
            # Wait two seconds between connection attempts.
            if now < self.retry_at:
                return

            self.retry_at = now + 2

            try:
                # Import here so simulation can run without pyserial installed.
                import serial

                # A zero timeout keeps serial reads from holding up the GUI.
                self.serial = serial.Serial(
                    self.args.port,
                    self.args.baud,
                    timeout=0,
                    write_timeout=0
                )

                # Start with an empty buffer whenever the port is reopened.
                self.lines = Lines()
                self.connection = 'UART OPEN - WAITING FOR DATA'

            except (ImportError, OSError) as exc:
                self.connection = f'UART UNAVAILABLE: {exc}'

            return

        try:
            # Only read what's available, with a limit on work per update.
            chunk = self.serial.read(min(self.serial.in_waiting, 8192))

            # A read might contain half a message or several messages.
            # Lines.feed() gives us only the completed ones.
            for line in self.lines.feed(chunk):
                if line and not self.data.feed(line, now):
                    self.bad_frames += 1

            # This means at least one reading is fresh, not necessarily all of them.
            live = any(
                self.data.get(k, now) is not None
                for k in self.data.times
            )

            self.connection = 'UART LIVE' if live else 'NO FRESH TELEMETRY'

        except OSError:
            # Clear the readings after a disconnect instead of leaving old
            # numbers on the screen while we try to reconnect.
            self.serial.close()
            self.serial = None
            self.data.clear()
            self.connection = 'UART DISCONNECTED'

    def draw(self, now):
        c = self.canvas

        # Redraw the dashboard using the latest readings and window size.
        c.delete('all')
        w, h = c.winfo_width(), c.winfo_height()

        # The canvas can briefly be tiny while the window is starting.
        if w < 10 or h < 10:
            return

        # Scale fonts relative to the original 1000x600 window.
        scale = min(w / 1000, h / 600)

        def text(x, y, value, size=20, color=WHITE, anchor='center'):
            # Positions are fractions of the window, so .5 is the midpoint.
            c.create_text(
                x * w,
                y * h,
                text=value,
                fill=color,
                anchor=anchor,
                font=('DejaVu Sans', max(8, int(size * scale)), 'bold')
            )

        def panel(x1, y1, x2, y2):
            c.create_rectangle(
                x1 * w,
                y1 * h,
                x2 * w,
                y2 * h,
                fill=PANEL,
                outline=''
            )

        def fmt(key, divisor=1, digits=1):
            # Missing or stale readings show dashes.
            # The divisor lets us convert watts to kW when needed.
            value = self.data.get(key, now)
            return '--' if value is None else f'{value/divisor:.{digits}f}'

        # Header: event mode on the left, data source on the right.
        mode = self.data.get('mode', now)

        text(
            .025, .055,
            'FSAE  |  ' + MODES.get(mode, 'MODE --'),
            22,
            anchor='w'
        )

        text(
            .975, .055,
            'DEMO DATA' if not self.args.port else 'LIVE INPUT',
            18,
            GREEN if not self.args.port else MUTED,
            anchor='e'
        )

        # Power gets the most space because it's the main driver priority.
        for x1, x2, label, key in [
            (.02, .49, 'INSTANT POWER', 'pwr'),
            (.51, .98, 'AVERAGE POWER', 'avg_pwr')
        ]:
            panel(x1, .12, x2, .49)
            mid = (x1 + x2) / 2

            text(mid, .18, label, 22, MUTED)

            text(
                mid, .31,
                fmt(key, 1000),
                80,
                GREEN if self.data.get(key, now) is not None else MUTED
            )

            text(mid, .43, 'kW', 22, MUTED)

        # Smaller readings underneath the two power panels.
        text(
            .025, .55,
            f'TC {fmt("tc", digits=0)}    REGEN {fmt("regen", digits=0)}',
            22,
            anchor='w'
        )

        text(
            .975, .55,
            f'LIMIT {fmt("draw_limit", 1000)} kW',
            22,
            anchor='e'
        )

        # Pack voltage, cell voltages, and temperatures share this panel.
        panel(.02, .61, .98, .78)

        text(
            .04, .65,
            f'PACK {fmt("acc_v")} V    '
            f'CELL {fmt("min_v", digits=2)} / {fmt("max_v", digits=2)} V',
            18,
            anchor='w'
        )

        text(
            .04, .73,
            f'TEMP C   PACK {fmt("acc_t", digits=0)}   '
            f'MOTOR {fmt("mtr_t", digits=0)}   '
            f'CTRL {fmt("cnt_t", digits=0)}   '
            f'COOL {fmt("cool_t", digits=0)}',
            18,
            anchor='w'
        )

        # These stay optional until we decide whether the drivers need them.
        if self.args.show_speed:
            text(
                .975, .82,
                f'{fmt("speed")} km/h',
                18,
                anchor='e'
            )

        if self.args.show_pedals:
            text(
                .025, .82,
                f'THROTTLE {fmt("gas", digits=0)}%    '
                f'BRAKE {fmt("brk", digits=0)}%',
                18,
                anchor='w'
            )

        # Build a list of any faults currently reported as active.
        active = [
            name
            for name, key in [
                ('BMS', 'fault_bms'),
                ('IMD', 'fault_imd'),
                ('BSPD', 'fault_bspd')
            ]
            if self.data.get(key, now) == 1
        ]

        # Don't treat missing status messages as a clear fault state.
        missing = any(
            self.data.get(k, now) is None
            for k in [
                'fault_bms',
                'fault_imd',
                'fault_bspd',
                'status',
                'ts_active'
            ]
        )

        state = self.data.get('status', now)

        message = (
            'FAULT: ' + ' / '.join(active)
            if active
            else (
                'STATUS DATA MISSING'
                if missing
                else (
                    'DRIVE ENABLED'
                    if state == 1
                    else 'DRIVE DISABLED'
                )
            )
        )

        # TS is displayed separately from the drive-enabled state.
        ts = self.data.get('ts_active', now)

        message += '  |  TS ' + (
            '--'
            if ts is None
            else ('ACTIVE' if ts == 1 else 'INACTIVE')
        )

        text(
            .5, .88,
            message,
            22,
            RED if active else MUTED if missing else GREEN
        )

        # Keep long serial error messages from taking over the footer.
        text(
            .025, .965,
            self.connection[:75],
            14,
            MUTED,
            anchor='w'
        )

        # INVALID is a parser debugging counter, not a vehicle fault.
        text(
            .975, .965,
            f'INVALID {self.bad_frames}  |  F11 FULLSCREEN',
            12,
            MUTED,
            anchor='e'
        )

    def tick(self):
        now = time.monotonic()
        self.receive(now)
        self.draw(now)

        # Schedule another update without blocking Tkinter's event loop.
        self.root.after(50, self.tick)

    def close(self):
        # Release the UART port before closing the window.
        if self.serial is not None:
            self.serial.close()

        self.root.destroy()


def main():
    # These options let us change the setup without editing the code.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='UART device; omit for simulation')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--stale', type=float, default=1.5)
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--show-speed', action='store_true')
    parser.add_argument('--show-pedals', action='store_true')
    args = parser.parse_args()

    if args.stale <= 0 or args.baud <= 0:
        parser.error('stale and baud must be positive')

    root = tk.Tk()
    Dashboard(root, args)
    root.mainloop()


# Only start the GUI when this file is run directly.
if __name__ == '__main__':
    main()