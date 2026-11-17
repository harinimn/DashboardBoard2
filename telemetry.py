"""Read UART messages and keep track of when each reading arrived."""

import math
import time


# Keep the old field names where possible so the message format stays familiar.
# All recognized values are numeric, including modes and fault flags.
FIELDS = {
    'pwr', 'avg_pwr', 'mtr_s', 'speed', 'acc_v', 'min_v', 'max_v',
    'acc_t', 'mtr_t', 'cnt_t', 'cool_t', 'status', 'mode', 'tc', 'regen',
    'draw_limit', 'gas', 'brk', 'fault_bms', 'fault_imd', 'fault_bspd',
    'ts_active'
}

# The STM32 sends a number; the dashboard turns it into a label.
MODES = {
    0: 'TEST',
    1: 'ENDURANCE',
    2: 'AUTOCROSS',
    3: 'SKIDPAD',
    4: 'ACCEL'
}


class Telemetry:
    def __init__(self, stale=1.5):
        # A reading is considered stale after this many seconds.
        self.stale = stale

        # Store each value alongside its most recent arrival time.
        self.values = {}
        self.times = {}

    def feed(self, line, now=None):
        """Read one key=value message or a comma-separated batch.

        For real telemetry, average power is supplied by the STM32.
        This parser only stores it.
        """

        now = time.monotonic() if now is None else now

        # Hold the new readings here until the whole message is checked.
        # That way, a bad batch doesn't leave us with half an update.
        pending = {}

        try:
            for pair in line.strip().split(','):
                key, raw = pair.split('=', 1)
                key = key.strip()

                # Ignore fields the dashboard doesn't currently use.
                if key not in FIELDS:
                    continue

                value = float(raw)

                # float() also accepts nan and inf, which aren't useful readings.
                if not math.isfinite(value):
                    return False

                pending[key] = value

        except ValueError:
            # This covers missing '=' signs and values that aren't numbers.
            return False

        # Only commit the readings once the message has passed the checks.
        self.values.update(pending)
        self.times.update({key: now for key in pending})

        # False means the message didn't contain any accepted readings.
        return bool(pending)

    def get(self, key, now=None):
        now = time.monotonic() if now is None else now

        # Each field expires independently. Fresh power data shouldn't
        # make an old temperature reading look fresh too.
        if key not in self.times or now - self.times[key] > self.stale:
            return None

        return self.values[key]

    def clear(self):
        # Used after a disconnect so old readings don't carry over.
        self.values.clear()
        self.times.clear()


class Lines:
    """Collect incoming UART bytes until a complete line is available."""

    def __init__(self):
        self.buffer = bytearray()

        # If a message gets too long, ignore the rest until its newline.
        self.dropping = False

    def feed(self, chunk):
        result = []

        for byte in chunk:
            # ASCII 10 is the newline marking the end of a message.
            if byte == 10:
                if not self.dropping:
                    try:
                        result.append(self.buffer.decode('ascii').strip())

                    except UnicodeDecodeError:
                        # Skip messages containing bytes we can't decode.
                        pass

                # Start fresh for the next message.
                self.buffer.clear()
                self.dropping = False

            elif not self.dropping:
                # Keep incomplete messages between calls to feed().
                self.buffer.append(byte)

                # Prevent a missing newline from growing the buffer forever.
                if len(self.buffer) > 2048:
                    self.buffer.clear()
                    self.dropping = True

        # One UART read can contain several complete messages.
        return result