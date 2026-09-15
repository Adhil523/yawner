from collections.abc import Iterator

import pytest

pytest.importorskip("gpiozero")

from gpiozero import Device  # noqa: E402
from gpiozero.pins.mock import MockFactory  # noqa: E402

from player.sensor import GpioSensor  # noqa: E402

PIN = 17


@pytest.fixture
def factory() -> Iterator[MockFactory]:
    mock = MockFactory()
    yield mock
    mock.reset()
    Device.pin_factory = None


def test_follows_the_pin(factory: MockFactory) -> None:
    sensor = GpioSensor(PIN, pin_factory=factory)
    pin = factory.pin(PIN)
    assert sensor.raw(0.0) is False
    pin.drive_high()
    assert sensor.raw(0.0) is True
    pin.drive_low()
    assert sensor.raw(0.0) is False
    sensor.close()


def test_pin_in_use_is_a_clear_error(factory: MockFactory) -> None:
    first = GpioSensor(PIN, pin_factory=factory)
    with pytest.raises(RuntimeError, match=f"GPIO{PIN}"):
        GpioSensor(PIN, pin_factory=factory)
    first.close()
