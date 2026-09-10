# Yawn Kiosk — Agent Execution Brief

You are building a small Raspberry Pi kiosk. A video of a man is shown fullscreen. While nobody is near a presence sensor, he stands idle. When someone arrives, he yawns. Every transition between idle and yawn must be visually seamless — no jumps, pops, or jolts.

Read this whole file before starting. Work in the phases below, in order, and stop at every **CHECKPOINT** to get confirmation from the human before continuing.

> **Decisions made since this brief was written** are in [docs/setup.md](docs/setup.md) and override it where they conflict: a single source clip (still → yawn → still) instead of two clips, and PC-only development with a simulated sensor for now.

---

## 1. The human you are working with

- Experienced software developer. Comfortable with Python, Git, CLI, SSH.
- **No hardware experience.** Any step involving wires, pins, or power must be explained in plain language, with both BCM GPIO numbers and physical pin numbers, and must be confirmed by the human. You cannot touch hardware; they can.
- They have two source videos: one of the man standing still (`idle`), one of him yawning (`yawn`).

## 2. Ask these questions first (before writing code)

Collect answers and record them in `docs/setup.md`:

1. Raspberry Pi model (3B+/4/5) and RAM size.
2. OS: Raspberry Pi OS Bookworm Desktop or Lite? 64-bit?
3. Display: resolution and how it's connected (HDMI monitor, TV, official touchscreen).
4. Sensor: exact model (e.g. HC-SR501 PIR, LD2410 mmWave, AM312). If unknown, ask for a photo or the text printed on the board.
5. Where the videos are, and whether they have audio that matters (default assumption: no audio, strip it).
6. Was the camera on a tripod for both clips? Is re-shooting possible? (Affects how much alignment work is needed.)
7. Where will the agent run: on the dev PC (preferred for analysis), on the Pi, or both? How to reach the Pi (SSH host/user)?

Do not guess on sensor voltage or Pi model — they change wiring and library choices.

## 3. Architecture overview

Three independent parts:

| Part | Runs on | Purpose |
|---|---|---|
| **Sensor layer** | Pi | Read a boolean presence signal from GPIO, debounce it. |
| **Offline analysis** | Dev PC | Analyse both videos, find seamless transition points ("portals"), render bridge frames, produce a manifest. |
| **Player** | Pi (also runs on PC with a fake sensor) | Fixed-clock fullscreen renderer driven by a state machine that only switches at precomputed portals. |

Key principle: **all expensive work happens offline.** The Pi never analyses video; it only plays frames according to a precomputed graph.

The approach is based on *Video Textures* (Schödl, Szeliski, Salesin, Essa — SIGGRAPH 2000). Frames are nodes; you may only jump between frames that are visually and dynamically near-identical.

## 4. Repository layout

Create this structure (adjust if there's good reason, but explain why):

```
yawn-kiosk/
├── CLAUDE.md                  # this file
├── README.md                  # human-facing: how to build, run, deploy
├── requirements-analysis.txt  # PC: opencv-python, numpy, scipy, tqdm, (optional) torch for RIFE
├── requirements-player.txt    # Pi: numpy, pygame, gpiozero, opencv-python-headless (or system python3-opencv)
├── docs/
│   ├── setup.md               # answers from section 2
│   ├── wiring.md              # wiring instructions + photo checklist
│   └── analysis-report.md     # generated: portal costs, chosen portals, review notes
├── assets/raw/                # idle.mp4, yawn.mp4 — never modified, gitignored
├── build/                     # all generated output, gitignored
│   ├── frames/ or clips/
│   ├── manifest.json
│   └── preview/
├── analysis/
│   ├── probe.py               # ffprobe metadata + sanity checks
│   ├── normalize.py           # fps/resolution/color normalisation, optional alignment
│   ├── features.py            # frame descriptors for comparison
│   ├── find_loop.py           # seamless idle loop
│   ├── find_portals.py        # entry + exit portals
│   ├── bridges.py             # crossfade / interpolation bridge frames
│   ├── export.py              # writes build/ assets + manifest.json
│   └── preview.py             # simulated-trigger preview video + portal contact sheets
├── player/
│   ├── config.toml
│   ├── sensor.py              # GpioSensor, KeyboardSensor, ScriptedSensor; debounce
│   ├── state_machine.py       # pure logic, no I/O, injectable clock
│   ├── frames.py              # load manifest + frames into RAM
│   └── main.py                # render loop
├── tools/
│   └── sensor_test.py         # prints presence changes; for wiring bring-up
├── deploy/
│   ├── install.sh
│   └── yawn-kiosk.service     # systemd unit
└── tests/
    ├── test_state_machine.py
    ├── test_debounce.py
    └── test_portals.py        # on synthetic frames
```

## 5. Phases

### Phase 0 — Inventory

- Set up the repo, venv, `.gitignore`.
- `analysis/probe.py`: report resolution, fps, frame count, duration, codec, pixel format, audio presence for both clips.
- Flag problems: fps mismatch, resolution mismatch, variable frame rate, interlacing, very short idle clip (< 3 s), heavy compression noise.
- Plan normalisation: both clips to the same constant fps and a target resolution matching the display (720p is a sensible default on Pi 4; 1080p is fine on Pi 5 if memory allows).

**CHECKPOINT 0:** Show the probe report and the normalisation plan.

### Phase 1 — Sensor bring-up (human-in-the-loop)

1. Write `docs/wiring.md` for the specific sensor model. Always include:
   - **Power off the Pi before wiring.**
   - Sensor VCC → Pi 5V (physical pin 2 or 4) — unless the sensor is a 3.3V part, then 3.3V (pin 1).
   - Sensor GND → Pi GND (physical pin 6).
   - Sensor OUT → **GPIO17 (physical pin 11)**.
   - Confirm the OUT signal is **3.3V logic**. HC-SR501, AM312 and LD2410 OUT are 3.3V and safe. If the sensor outputs 5V, a voltage divider is mandatory (e.g. 10 kΩ / 20 kΩ); explain it step by step. **Never** tell the human to connect a 5V signal directly to a GPIO pin.
   - Sensor-specific notes: HC-SR501 has two potentiometers (sensitivity, hold time) and a jumper (set to repeat/"H" mode); set hold time to minimum. PIR needs ~30–60 s warm-up after power-on during which output is unreliable.
2. Write `tools/sensor_test.py` using **gpiozero** (`DigitalInputDevice(17)`), printing timestamped state changes. Do not use `RPi.GPIO` (doesn't work on Pi 5).
3. On Bookworm, pip requires a venv. Create it with `--system-site-packages` so the system `gpiozero`/`lgpio` packages are visible.

**CHECKPOINT 1:** Human wires the sensor, runs `sensor_test.py`, walks in and out of range, and reports the output. Proceed only once they see clean transitions.

### Phase 2 — Offline analysis (dev PC)

#### 2a. Normalise and align
- Transcode both clips to the same constant fps and target resolution, no audio. Keep originals untouched.
- Check for camera drift between clips: compare mean frames of each clip, estimate a transform with `cv2.findTransformECC` (start with `MOTION_TRANSLATION`, escalate to `MOTION_EUCLIDEAN` only if needed). Apply to the yawn clip if the offset is > ~1 px.
- Check lighting/colour mismatch (per-channel mean/std on the static background). If different, apply a simple colour transfer to the yawn clip.

#### 2b. Frame descriptors
- Per frame: downscale (e.g. 160×90), grayscale, light Gaussian blur, float32.
- Frame distance `d(a, b)` = mean absolute difference. Optionally weight a region around the person more heavily than the static background (derive the region from per-pixel temporal variance across both clips).

#### 2c. Windowed (dynamics-aware) distance
Single-frame matches aren't enough: two frames can share a pose while moving in opposite directions, which reads as a jolt. Use a window:

```
D(i, j) = Σ_{k=-m..m} w_k · d(A[i+k], B[j+k])     # e.g. m = 2..3, binomial weights
```

A transition "from A frame i to B frame j" means: show A[i], then B[j+1]. Low `D(i, j)` means both the pose and the motion around the cut agree. Handle clip boundaries by truncating the window and renormalising weights.

#### 2d. Seamless idle loop
- Find `(a, b)` with `b − a ≥ min_loop_len` (e.g. 3 s, or as long as the clip allows) minimising `D_idle(b, a)`. The idle loop plays `a..b` and jumps from `b` back to `a`.
- If the best loop still has visible mismatch, it gets a bridge like any other portal (2g).

#### 2e. Entry portals (idle → yawn)
- Detect where the actual yawn motion begins in the yawn clip (motion-energy onset). Frames before onset are a "lead-in" and are great candidates for entry targets — the man is still in neutral pose there.
- Compute `D(i, j)` for all idle-loop frames `i` and yawn lead-in frames `j`.
- Select a **set** of entry portals spread through the idle loop: non-maximum suppression over `i` so consecutive portals are ≤ `max_entry_latency` apart (default 1.5 s), keeping the lowest-cost candidate in each window. Worst-case reaction delay = largest gap between portals.
- Report cost of every chosen portal. Portals above a threshold (calibrate against the loop seam cost and against natural frame-to-frame differences within the idle clip) are flagged for review.

#### 2f. Exit portals (yawn → idle)
- Same idea on the tail: frames after the yawn motion ends (motion offset) vs. idle-loop frames. Pick the best few exits; the player may use any of them. After exit, idle resumes from the matched idle frame.

#### 2g. Bridges
- Default: short linear crossfade (4–8 frames) across each portal, rendered at full resolution offline.
- If a portal's cost is high enough that a crossfade ghosts visibly, optionally generate in-between frames with a frame-interpolation model (RIFE or FILM) on the dev PC. Treat this as an optional enhancement; ship without it if crossfades look fine.
- Bridge frames are pre-rendered; the Pi never blends at runtime.

#### 2h. Export
Write `build/manifest.json` describing a frame graph, e.g.:

```json
{
  "fps": 30,
  "resolution": [1280, 720],
  "sequences": {
    "idle": "build/clips/idle_loop.mp4",
    "yawn": "build/clips/yawn.mp4",
    "bridge_in_0": "build/clips/bridge_in_0.mp4"
  },
  "idle_loop": { "start": 0, "end": 212, "bridge": "bridge_loop" },
  "entries": [ { "idle_frame": 37, "bridge": "bridge_in_0", "yawn_frame": 12, "cost": 1.84 } ],
  "exits":   [ { "yawn_frame": 170, "bridge": "bridge_out_0", "idle_frame": 88, "cost": 2.10 } ]
}
```

Sequences may be stored as lossless/near-lossless video (e.g. `ffv1` or high-quality H.264) or image sequences — pick what decodes reliably on the Pi and document the choice.

#### 2i. Review artefacts
- `preview.py`: render a preview video simulating random presence events through the real state machine (reuse `player/state_machine.py` with a `ScriptedSensor`), so every seam type appears several times.
- Contact sheets per portal: the 3 frames before and after each cut, side by side, plus a difference heatmap.
- Write `docs/analysis-report.md` with the cost table and any flagged portals.

**CHECKPOINT 2:** Human watches the preview and reviews flagged portals. Iterate on window size, weights, crossfade length, or alignment until they approve. If no acceptable portals exist (e.g. camera moved, actor never returns to neutral), say so plainly and recommend a re-shoot with a tripod, locked exposure, and the actor starting and ending the yawn in the same marked neutral pose.

### Phase 3 — Player (develop on PC first)

#### Sensor abstraction (`player/sensor.py`)
- Common interface: `is_present() -> bool` (debounced), plus raw state for logging.
- `GpioSensor` (gpiozero, callbacks set a thread-safe flag), `KeyboardSensor` (hold/toggle a key — for dev on PC), `ScriptedSensor` (timed events — for tests and previews).
- Debounce: presence becomes true after raw signal is high for `presence_on_ms`; becomes false after raw low for `absence_off_s`.

#### State machine (`player/state_machine.py`)
Pure logic, no I/O, injectable clock, fully unit-tested. States:

```
IDLE       → play idle loop frame by frame.
             On each frame: if a yawn is armed AND current idle frame is an entry portal → ENTERING
ENTERING   → play the entry bridge → YAWNING (at yawn_frame)
YAWNING    → play yawn to completion (never interrupted, even if the person leaves)
             At the first reachable exit portal → EXITING
EXITING    → play exit bridge → IDLE (at exit's idle_frame)
```

Arming rules come from config (section 6). Decisions are made per frame, only at portal frames — never cut anywhere else.

#### Render loop (`player/main.py`)
- One thread owns a fixed frame clock (manifest fps). Use absolute deadlines (`next_deadline += 1/fps`) to avoid drift; if behind by more than a frame, skip ahead and log it.
- Display with **pygame** fullscreen, mouse cursor hidden. On Bookworm Desktop (Wayland) the default SDL driver works; on Lite, use `SDL_VIDEODRIVER=kmsdrm`. Verify which applies.
- Load all frames into RAM at startup, **pre-converted to pygame Surfaces** at display resolution so runtime is just blitting. Compute the memory budget first (720p RGB ≈ 2.7 MB/frame) and log it. If it exceeds ~60% of available RAM, fall back to storing JPEG bytes in RAM and decoding one frame ahead in a worker thread.
- No external players (VLC, mpv, omxplayer). Frame-accurate control is required.
- Log state transitions, portal used, and dropped frames to stdout (journald picks it up).

**CHECKPOINT 3:** Human runs the player on their PC with `KeyboardSensor` and confirms the behaviour and seams look right.

### Phase 4 — Deploy to the Pi

- `deploy/install.sh`: apt packages (e.g. `python3-pygame`, `python3-opencv`, `python3-gpiozero` where available), venv with `--system-site-packages`, copy `build/` and `player/`.
- `deploy/yawn-kiosk.service`: systemd unit, `Restart=always`, runs as the normal user, correct display environment for the chosen OS variant.
- Disable screen blanking (`raspi-config` → Display Options → Screen Blanking), hide cursor, optionally disable the desktop's own screensaver.
- Measure on the device: startup time, RAM usage, CPU usage, dropped frames over 10 minutes.

**CHECKPOINT 4:** Run a soak test (≥ 1 hour with real people or a scripted sensor). Report dropped frames and any errors.

### Phase 5 — Tuning
Adjust sensor potentiometers, debounce values, cooldown, and entry latency based on real-world use. Keep all tunables in `player/config.toml`.

## 6. Behaviour spec (defaults — all configurable)

```toml
[sensor]
gpio_pin = 17
presence_on_ms = 200        # raw high this long → present
absence_off_s = 5.0         # raw low this long → absent

[behaviour]
yawn_on_arrival = true      # one yawn per arrival
repeat_while_present = false
repeat_interval_s = 20.0    # only used if repeat_while_present
cooldown_s = 5.0            # after person leaves, before a new arrival can trigger
finish_yawn_if_left = true  # never interrupt a yawn

[video]
max_entry_latency_s = 1.5   # portal spacing target used during analysis
```

"Arrival" = debounced transition absent → present, respecting cooldown. A yawn is *armed* on arrival and consumed when an entry portal is taken.

## 7. Engineering rules

- Python 3.11+. Type hints. Small, readable modules.
- Analysis scripts are deterministic, CLI-driven (`argparse`), read from `assets/raw/`, write only to `build/`. Never modify raw assets.
- The state machine and debounce have no hardware or display dependencies and have unit tests.
- Everything runnable on the dev PC without a Pi (fake sensors, windowed mode flag `--windowed`).
- Prefer simple, well-understood methods (pixel differences, crossfades) before reaching for ML models.
- When a result depends on visual judgement, produce an artefact the human can look at rather than asserting it looks fine.

## 8. When to stop and ask

- Any wiring or power step.
- Unknown sensor model or output voltage.
- Portals that exceed the quality threshold, or no good portals found.
- Proposing a re-shoot.
- Anything that needs credentials, SSH access, or `sudo` on the Pi.
- Any deviation from this plan that changes the architecture.

## 9. Definition of done

- Pi boots straight into the fullscreen idle loop, with no desktop visible.
- Walking into range triggers a yawn within `max_entry_latency_s`; the transition is not noticeable to a casual viewer.
- The yawn always completes and returns to idle seamlessly.
- The idle loop point is not noticeable.
- No dropped frames during normal operation; service recovers automatically from a crash.
- `README.md` explains how to re-run analysis with new videos and redeploy.