# Sensor wiring (brief Phase 1)

**Hardware:** Raspberry Pi 5 + **Waveshare HMMD Human Micro-Motion Detection 24 GHz mmWave sensor** (S3KM1110 chip), connected over the serial port (UART).

This is the wiring and setup from the working prototype (`yawn-signage`), which already detects people on this exact hardware. If your Pi is already set up and wired that way, skip to [section 5](#5-test-it).

## 1. Two facts that keep the Pi and sensor safe

- **This sensor runs on 3.3V, not 5V.** It accepts 3.0–3.6V. Connecting it to a 5V pin can damage it.
- **The Pi's GPIO pins only accept 3.3V signals.** The sensor also works at 3.3V, so its TX pin is safe to connect straight to the Pi. No resistors are needed.

## 2. Finding the pins

The Pi 5 has a 40-pin header along one long edge. Pins have two numbering schemes:
- **Physical number:** position on the header, 1–40.
- **GPIO (BCM) number:** the name the software uses, e.g. GPIO14.

To find pin 1, hold the Pi so the 40-pin header runs along the **top edge** and the USB/Ethernet ports face **right**:
- The **bottom row** (nearer the middle of the board) holds the odd pins, 1, 3, 5 … 39, from left to right.
- The **top row** (along the board's edge) holds the even pins, 2, 4, 6 … 40, from left to right.
- Pin 1 is **bottom-left**. To double-check on the Pi, run `pinout` in a terminal; it prints a diagram.

## 3. Wiring

**Shut down and unplug the Pi first:** run `sudo shutdown now`, wait for the green light to stop blinking, then pull the power cable. Never change wires on a powered Pi.

| HMMD pin | Pi 5 physical pin | Pi pin name |
|---|---|---|
| **3V3** | **Pin 1** | 3.3V power. **Not** pin 2 or 4, which are 5V. |
| **GND** | **Pin 6** | Ground |
| **TX** | **Pin 10** | GPIO15 / RXD (Pi receives) |
| **RX** | **Pin 8** | GPIO14 / TXD (Pi sends) |
| OT2 | Leave unconnected | Not needed |

**Why TX goes to RX:** each side *talks* on TX and *listens* on RX. The sensor's TX (talk) connects to the Pi's RX (listen), and the other way round. Connecting TX to TX is the most common serial wiring mistake. It doesn't damage anything, but no data arrives.

You need 4 female-to-female jumper wires. Before powering on, check each wire end against the table. If you want a second check, send me a photo that shows both ends of every wire.

## 4. Pi 5 serial setup (once)

These steps come from the prototype's README.

1. Packages: `deploy/run-pi.sh` installs what's missing when you first run it, so there's nothing to do here.
2. Turn on the header serial port. Open the boot config:
   ```sh
   sudo nano /boot/firmware/config.txt
   ```
   Add this line under the `[all]` section, save (Ctrl+O, Enter) and exit (Ctrl+X):
   ```ini
   dtoverlay=uart0-pi5
   ```
3. Run `sudo raspi-config` → **Interface Options** → **Serial Port**:
   - "Would you like a login shell to be accessible over serial?" → **No**
   - "Would you like the serial port hardware to be enabled?" → **Yes**
4. Reboot: `sudo reboot`
5. Check that the port exists:
   ```sh
   ls -l /dev/ttyAMA0
   ```

**Why `/dev/ttyAMA0` and not `/dev/serial0`:** on a Pi 5, `serial0` is a separate 3-pin debug connector, not the 40-pin header. The player picks `ttyAMA0` automatically on a Pi 5 (`serial_device = "auto"` in [player/config.toml](../player/config.toml)).

## 5. Test it

From the repo root on the Pi:

```sh
deploy/run-pi.sh sensor-test
```

This installs any missing packages, checks the serial port, then runs `python3 -m tools.sensor_test`.

It prints two lines a second: whether the sensor sees someone, how far away they are, and whether that counts as **in the zone**. The zone is 50–200 cm by default, and someone stays counted until they're gone or 260 cm away.

1. Stand out of range for a few seconds.
2. Walk toward the sensor to about 1 m away, and stay there for about 10 seconds.
3. Walk away, beyond about 3 m, and wait about 10 seconds.
4. Repeat 3 times, press Ctrl+C, and **paste the output here**.

What "working" looks like: `ENTERED zone` when you come close and `LEFT zone` after you move away. The distance should roughly match where you're standing, and there should be no flickering between yes and no while you stand still.

| You see | Likely cause |
|---|---|
| `could not open port /dev/ttyAMA0` | Section 4 not done or no reboot. Check that `dtoverlay=uart0-pi5` is under `[all]`. |
| `Permission denied` on the port | Your user isn't in the `dialout` group: `sudo usermod -aG dialout $USER`, then log out and back in. |
| `no data for …` (port opens but nothing arrives) | TX/RX swapped, sensor not powered (3V3/GND), or a loose wire. **Shut down first**, then check. |
| Presence yes but never `in_zone` | Standing closer than 50 cm or further than 200 cm. Adjust `min_cm`/`max_cm` in `player/config.toml`. |
| Triggers from people far away | Lower `max_cm` and `rearm_cm`. |

Once the readings look right, `deploy/run-pi.sh` starts the kiosk with the same sensor.

## Alternative: OT2 on/off output (not used)

The HMMD also has an OT2 pin that is simply HIGH while someone is present, with no distance. The player supports it with `--sensor gpio` (OT2 → pin 11 / GPIO17). We use the serial link instead because it's already wired and working, and its distance zone ignores people passing further away.
