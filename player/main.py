"""Yawn kiosk player: the idle loop, yawning when someone arrives.

    python -m player.main [--windowed] [--hud] [--sensor keyboard|scripted|hmmd|gpio] [--frames auto|surfaces|jpeg]

keyboard (default): hold SPACE while someone is "present", or press T to toggle presence.
scripted: random visits (repeatable with --seed) for unattended soak tests.
hmmd: the Waveshare HMMD mmWave sensor over UART, settings in config.toml [sensor] (Pi only).
gpio: a plain on/off sensor output on [sensor] gpio_pin (Pi only).
Q or Esc quits.
"""

import argparse
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

import pygame

from player.frames import FRAME_MODES, FrameMode, FrameStore, load_frames, load_manifest
from player.hmmd import HmmdSensor, pyserial_opener
from player.sensor import Debouncer, GpioSensor, KeyboardSensor, ScriptedSensor, Sensor, random_visits, visit_events
from player.settings import DEFAULT_CONFIG, SensorSettings, Settings, load_settings
from player.state_machine import Behaviour, Graph, YawnStateMachine

log = logging.getLogger("player")

SENSORS = ("keyboard", "scripted", "hmmd", "gpio")
DEFAULT_SEED = 7
SCRIPTED_HOURS = 24  # length of the scripted visit schedule; long enough for any soak test
SECONDS_PER_HOUR = 3600
FAST_ABSENCE_OFF_S = 0.2
FAST_COOLDOWN_S = 1.5  # zone must stay empty this long before a new arrival counts (prototype's re-arm time)
WINDOW_SCREEN_FRACTION = 0.9
QUIT_KEYS = {"q", "escape"}
BLACK = (0, 0, 0)
HUD_TEXT = (255, 255, 255)
HUD_BACKGROUND = (0, 0, 0, 160)


def fit(video: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    """Largest even size with the video's aspect ratio that fits inside `box`."""
    scale = min(box[0] / video[0], box[1] / video[1])
    return int(video[0] * scale) // 2 * 2, int(video[1] * scale) // 2 * 2


def open_display(video: tuple[int, int], windowed: bool) -> tuple[pygame.Surface, tuple[int, int], tuple[int, int]]:
    """Returns (screen, video size on screen, top-left offset of the video)."""
    if windowed:
        desktop = pygame.display.get_desktop_sizes()[0]
        box = (int(desktop[0] * WINDOW_SCREEN_FRACTION), int(desktop[1] * WINDOW_SCREEN_FRACTION))
        size = fit(video, box)
        return pygame.display.set_mode(size), size, (0, 0)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    size = fit(video, screen.get_size())
    offset = ((screen.get_width() - size[0]) // 2, (screen.get_height() - size[1]) // 2)
    return screen, size, offset


def _sleep_until(deadline: float) -> None:
    remaining = deadline - time.perf_counter()
    if remaining > 0.002:
        time.sleep(remaining - 0.001)
    while time.perf_counter() < deadline:
        pass


def _draw_hud(screen: pygame.Surface, font: pygame.font.Font, text: str, offset: tuple[int, int]) -> None:
    rendered = font.render(text, True, HUD_TEXT)
    backing = pygame.Surface((rendered.get_width() + 12, rendered.get_height() + 8), pygame.SRCALPHA)
    backing.fill(HUD_BACKGROUND)
    screen.blit(backing, (offset[0] + 8, offset[1] + 8))
    screen.blit(rendered, (offset[0] + 14, offset[1] + 12))


def _advance(machine: YawnStateMachine, present: bool, now: float) -> None:
    before = machine.phase
    machine.advance(present, now)
    jump = machine.last_jump
    if jump is not None and jump.bridge != "bridge_loop":
        via = f"crossfade {jump.bridge}" if jump.bridge else "no cut"
        log.info("jump %d -> %d (%s)", jump.at, jump.resume, via)
    if machine.phase is not before:
        log.info("%s -> %s", before.value, machine.phase.value)


def make_sensor(kind: str, seed: int, sensor_settings: SensorSettings, behaviour: Behaviour) -> Sensor:
    if kind == "keyboard":
        log.info("sensor: keyboard; hold SPACE (or press T) for 'someone present'")
        return KeyboardSensor()
    if kind == "hmmd":
        log.info("sensor: HMMD mmWave on %s, zone %d-%d cm (clears at %d cm)", sensor_settings.serial_device,
                 sensor_settings.min_cm, sensor_settings.max_cm, sensor_settings.rearm_cm)
        return HmmdSensor(pyserial_opener(sensor_settings.serial_device, sensor_settings.baud), sensor_settings.zone())
    if kind == "gpio":
        log.info("sensor: GPIO%d (BCM); some sensors need up to a minute after power-on before readings are reliable",
                 sensor_settings.gpio_pin)
        return GpioSensor(sensor_settings.gpio_pin)
    seconds = SCRIPTED_HOURS * SECONDS_PER_HOUR
    visits = random_visits(seconds, seed, sensor_settings.absence_off_s, behaviour.cooldown_s)
    log.info("sensor: scripted, %d visits over %d h (seed %d)", len(visits), SCRIPTED_HOURS, seed)
    return ScriptedSensor(visit_events(visits))


def run(settings: Settings, windowed: bool, hud: bool, fast_input: bool, sensor_kind: str, seed: int,
        frame_mode: FrameMode) -> None:
    manifest = load_manifest(settings.manifest)
    graph = Graph.from_manifest(manifest)
    fps = float(manifest["fps"])

    pygame.init()
    pygame.display.set_caption("Yawn Kiosk")
    screen, size, offset = open_display((manifest["resolution"][0], manifest["resolution"][1]), windowed)
    screen.fill(BLACK)
    started = time.perf_counter()
    frames = load_frames(manifest, settings.manifest.parent, size, frame_mode)
    try:
        if fast_input:
            sensor_settings = replace(settings.sensor, absence_off_s=FAST_ABSENCE_OFF_S)
            behaviour = replace(settings.behaviour, cooldown_s=FAST_COOLDOWN_S)
            log.info("fast input: gone after %.1f s, new arrival counts after %.1f s empty",
                     FAST_ABSENCE_OFF_S, FAST_COOLDOWN_S)
        else:
            sensor_settings = settings.sensor
            behaviour = settings.behaviour
        sensor = make_sensor(sensor_kind, seed, sensor_settings, behaviour)
        try:
            log.info("ready in %.1f s; Q to quit", time.perf_counter() - started)
            debouncer = Debouncer(sensor_settings.presence_on_s, sensor_settings.absence_off_s)
            _play(screen, offset, frames, fps, sensor, debouncer, YawnStateMachine(graph, behaviour), hud)
        finally:
            sensor.close()
    finally:
        frames.close()


def _play(screen: pygame.Surface, offset: tuple[int, int], frames: FrameStore, fps: float,
          sensor: Sensor, debouncer: Debouncer, machine: YawnStateMachine, hud: bool) -> None:
    font = pygame.font.Font(None, 30) if hud else None
    period = 1.0 / fps
    playback_start = deadline = time.perf_counter()
    present = False
    dropped = 0
    frames.prepare(machine.current)

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type in (pygame.KEYDOWN, pygame.KEYUP):
                key = pygame.key.name(event.key)
                if event.type == pygame.KEYDOWN and key in QUIT_KEYS:
                    return
                if isinstance(sensor, KeyboardSensor):
                    sensor.handle_key(key, event.type == pygame.KEYDOWN)

        now = time.perf_counter()
        was_present, present = present, debouncer.update(sensor.raw(now - playback_start), now)
        if present != was_present:
            log.info("presence: %s", "someone there" if present else "nobody")

        name, index = machine.current
        screen.blit(frames.get(machine.current), offset)
        if font is not None:
            status = f"{machine.phase.value}  {name}:{index}  present={'yes' if present else 'no'}"
            _draw_hud(screen, font, status + ("  armed" if machine.armed else ""), offset)
        pygame.display.flip()

        _advance(machine, present, now)
        deadline += period
        late = time.perf_counter() - deadline
        if late > period:  # more than a frame behind: skip ahead rather than drift
            missed = int(late // period)
            for _ in range(missed):
                _advance(machine, present, now)
            deadline += missed * period
            dropped += missed
            log.warning("behind schedule, skipped %d frame(s) (%d total)", missed, dropped)
        frames.prepare(machine.current)
        _sleep_until(deadline)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--windowed", action="store_true", help="run in a window instead of fullscreen")
    parser.add_argument("--hud", action="store_true", help="show state, frame and presence in the corner")
    parser.add_argument("--fast-input", action="store_true", help="gone after 0.2 s; a new arrival counts once nobody was there for 1.5 s")
    parser.add_argument("--sensor", choices=SENSORS, default="keyboard", help="where presence comes from")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="visit schedule for --sensor scripted")
    parser.add_argument("--frames", choices=FRAME_MODES, default="auto",
                        help="keep frames as Surfaces or JPEG bytes; auto picks by available RAM")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(name)s]: %(message)s")
    try:
        run(load_settings(args.config), args.windowed, args.hud, args.fast_input, args.sensor, args.seed, args.frames)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        log.error("%s", error)
        sys.exit(1)
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
