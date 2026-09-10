import numpy as np
import pytest

from analysis.features import motion_energy, pairwise_distance, scaled_size, windowed_distance


def _flat_frames(values: list[float]) -> np.ndarray:
    return np.stack([np.full((2, 2), value, dtype=np.float32) for value in values])


def test_scaled_size_keeps_aspect_with_even_sides() -> None:
    assert scaled_size(720, 1280, 160) == (90, 160)
    assert scaled_size(1920, 1080, 160) == (160, 90)


def test_pairwise_distance_is_mean_absolute_difference() -> None:
    a = _flat_frames([0, 4])
    b = _flat_frames([1])
    np.testing.assert_allclose(pairwise_distance(a, b), [[1.0], [3.0]])


def test_motion_energy_repeats_first_step() -> None:
    np.testing.assert_allclose(motion_energy(_flat_frames([0, 2, 5])), [2, 2, 3])


def test_windowed_distance_weights_and_renormalises_at_edges() -> None:
    distances = np.arange(16, dtype=np.float32).reshape(4, 4)  # d[i, j] = 4i + j
    windowed = windowed_distance(distances, (1.0, 2.0, 1.0))
    assert windowed[1, 1] == pytest.approx((0 + 2 * 5 + 10) / 4)
    assert windowed[0, 0] == pytest.approx((2 * 0 + 5) / 3)  # tap k=-1 is off both clips
    assert windowed[0, 3] == pytest.approx(3.0)  # only k=0 fits


def test_windowed_distance_penalises_same_pose_moving_the_other_way() -> None:
    rising = _flat_frames([0, 1, 2, 3, 4])
    falling = rising[::-1].copy()
    single = pairwise_distance(rising, falling)
    assert single[2, 2] == 0  # identical middle frame...
    assert windowed_distance(single)[2, 2] == pytest.approx(1.5)  # ...but opposite motion


def test_windowed_distance_rejects_even_window() -> None:
    with pytest.raises(ValueError):
        windowed_distance(np.zeros((3, 3), dtype=np.float32), (1.0, 1.0))
