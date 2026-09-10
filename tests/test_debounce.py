from player.sensor import Debouncer, KeyboardSensor, ScriptedSensor


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
