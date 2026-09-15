from player.sensor import Debouncer, KeyboardSensor, ScriptedSensor, random_visits, visit_events


def test_presence_needs_signal_held_for_on_time() -> None:
    debouncer = Debouncer(on_s=0.2, off_s=5.0)
    assert debouncer.update(True, 0.0) is False
    assert debouncer.update(True, 0.19) is False
    assert debouncer.update(True, 0.2) is True


def test_short_blip_is_ignored() -> None:
    debouncer = Debouncer(on_s=0.2, off_s=5.0)
    debouncer.update(True, 0.0)
    debouncer.update(False, 0.1)
    assert debouncer.update(False, 1.0) is False


def test_absence_needs_signal_low_for_off_time() -> None:
    debouncer = Debouncer(on_s=0.2, off_s=5.0)
    debouncer.update(True, 0.0)
    assert debouncer.update(True, 0.2) is True
    assert debouncer.update(False, 1.0) is True
    assert debouncer.update(True, 3.0) is True  # back before the timeout: still present
    assert debouncer.update(False, 4.0) is True
    assert debouncer.update(False, 8.99) is True
    assert debouncer.update(False, 9.0) is False


def test_scripted_sensor_replays_events() -> None:
    sensor = ScriptedSensor([(1.0, True), (3.0, False), (0.0, False)])
    assert [sensor.raw(t) for t in (-1.0, 0.5, 1.0, 2.9, 3.0)] == [False, False, True, True, False]


def test_keyboard_sensor_hold_and_toggle() -> None:
    sensor = KeyboardSensor()
    sensor.handle_key("space", True)
    assert sensor.raw(0.0) is True
    sensor.handle_key("space", False)
    assert sensor.raw(0.0) is False
    sensor.handle_key("t", True)
    sensor.handle_key("t", False)
    assert sensor.raw(0.0) is True
    sensor.handle_key("t", True)
    assert sensor.raw(0.0) is False


def test_random_visits_are_repeatable_and_spaced_past_debounce_and_cooldown() -> None:
    visits = random_visits(600.0, seed=3, absence_off_s=5.0, cooldown_s=5.0)
    assert visits == random_visits(600.0, seed=3, absence_off_s=5.0, cooldown_s=5.0)
    assert len(visits) > 5
    for (_, leave), (next_arrive, _) in zip(visits, visits[1:]):
        assert next_arrive - leave >= 10.0


def test_visit_events_drive_scripted_sensor() -> None:
    sensor = ScriptedSensor(visit_events([(2.0, 4.0), (10.0, 12.0)]))
    assert [sensor.raw(t) for t in (1.0, 2.0, 3.9, 4.0, 11.0, 13.0)] == [False, True, True, False, True, False]
