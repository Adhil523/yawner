"""Sensor bring-up: live readings from the HMMD mmWave sensor (brief Phase 1).

    python3 -m tools.sensor_test [--device auto] [--every 0.5]

Run on the Pi from the repo root, after the serial setup in docs/wiring.md.
Prints one line every `--every` seconds with presence, distance and whether
that counts as "in the zone" (the zone comes from player/config.toml), and
marks each zone change. No debouncing here on purpose: this is what the
sensor itself reports. Ctrl+C stops and prints a summary.
"""

import argparse
import logging
import sys
import time
from datetime import datetime

from player.hmmd import HmmdSensor, pyserial_opener
from player.settings import DEFAULT_CONFIG, load_settings

log = logging.getLogger("sensor_test")

DEFAULT_EVERY_S = 0.5


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default=None, help="serial device (default: serial_device from config.toml)")
    parser.add_argument("--every", type=float, default=DEFAULT_EVERY_S, help="seconds between printed lines")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s]: %(message)s")

    sensor_settings = load_settings(DEFAULT_CONFIG).sensor
    device = args.device or sensor_settings.serial_device
    try:
        sensor = HmmdSensor(pyserial_opener(device, sensor_settings.baud), sensor_settings.zone())
    except RuntimeError as error:
        sys.exit(f"[sensor_test]: {error}")

    log.info("reading %s at %d baud; zone %d-%d cm, clears at %d cm. Ctrl+C to stop.", device, sensor_settings.baud,
             sensor_settings.min_cm, sensor_settings.max_cm, sensor_settings.rearm_cm)
    started = time.monotonic()
    was_inside = False
    entries = 0
    try:
        while True:
            time.sleep(args.every)
            sample, inside, age = sensor.latest()
            stamp = f"{datetime.now():%H:%M:%S.%f}"[:-3]
            if sample is None or age > sensor.stale_s:
                print(f"{stamp}  no data for {age:.1f} s (check wiring and serial setup)", flush=True)
                continue
            change = ""
            if inside != was_inside:
                change = "  <-- ENTERED zone" if inside else "  <-- LEFT zone"
                entries += inside
                was_inside = inside
            print(
                f"{stamp}  present={'yes' if sample.present else 'no ':<3}  distance={sample.distance_cm:4d} cm"
                f"  in_zone={'yes' if inside else 'no '}{change}",
                flush=True,
            )
    except KeyboardInterrupt:
        pass
    finally:
        sensor.close()
    print(f"\n[sensor_test]: {time.monotonic() - started:.0f} s, entered the zone {entries} time(s).")


if __name__ == "__main__":
    main()
