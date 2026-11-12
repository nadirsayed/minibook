from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from minibook.market.curves import ZeroCurve, parallel, tent

# SYNTHETIC curve used throughout.
CURVE = ZeroCurve(
    "EUR", (0.5, 1.0, 2.0, 5.0), (0.020, 0.022, 0.025, 0.030), ("6M", "1Y", "2Y", "5Y")
)


def test_df_at_zero_is_one_and_pillars_exact() -> None:
    assert CURVE.df(0.0) == 1.0
    for t, z in zip(CURVE.times, CURVE.zeros, strict=True):
        assert CURVE.zero(t) == z
        assert CURVE.df(t) == pytest.approx(np.exp(-z * t), rel=1e-15)


def test_linear_interpolation_and_flat_extrapolation() -> None:
    assert CURVE.zero(1.5) == pytest.approx(0.0235)
    assert CURVE.zero(0.1) == 0.020
    assert CURVE.zero(30.0) == 0.030
    np.testing.assert_allclose(CURVE.zero(np.array([0.5, 3.5])), [0.020, 0.0275])


def test_forward_rate() -> None:
    f = CURVE.forward_rate(1.0, 2.0)
    assert f == pytest.approx((0.025 * 2 - 0.022 * 1) / 1.0)
    with pytest.raises(ValueError, match="t2 > t1"):
        CURVE.forward_rate(1.0, 1.0)


@pytest.mark.parametrize(
    ("times", "zeros", "msg"),
    [
        ((), (), "non-empty"),
        ((1.0, 0.5), (0.01, 0.01), "increasing"),
        ((0.0, 1.0), (0.01, 0.01), "positive"),
        ((1.0,), (float("nan"),), "finite"),
    ],
)
def test_invalid_curves(times: tuple[float, ...], zeros: tuple[float, ...], msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        ZeroCurve("X", times, zeros)


def test_label_lookup() -> None:
    assert CURVE.label_index("2Y") == 2
    with pytest.raises(KeyError, match="no pillar"):
        CURVE.label_index("7Y")


@given(st.lists(st.floats(0.05, 20.0), min_size=1, max_size=5))
def test_with_pillars_leaves_curve_unchanged(extra: list[float]) -> None:
    c = CURVE.with_pillars(extra, [f"x{i}" for i in range(len(extra))])
    grid = np.linspace(0.0, 25.0, 501)
    np.testing.assert_allclose(c.zero(grid), CURVE.zero(grid), atol=1e-15)


def test_with_pillars_keeps_existing_label() -> None:
    c = CURVE.with_pillars([1.0, 3.0], ["dup", "3Y"])
    assert c.labels == ("6M", "1Y", "2Y", "3Y", "5Y")


def test_tents_sum_to_parallel_and_shift_exact_off_pillar() -> None:
    knots = list(CURVE.times)
    summed = CURVE
    for i in range(len(knots)):
        summed = summed.shifted(tent(knots, i, 1e-4))
    par = CURVE.shifted(parallel(1e-4))
    grid = np.linspace(0.0, 10.0, 401)
    np.testing.assert_allclose(summed.zero(grid), par.zero(grid), atol=1e-16)
    # Tent with knots on pillars: the shifted curve is z(t) + tent(t) at every t.
    one = CURVE.shifted(tent(knots, 2, 1e-4))
    expected = np.asarray(CURVE.zero(grid)) + np.interp(grid, knots, [0, 0, 1e-4, 0])
    np.testing.assert_allclose(one.zero(grid), expected, atol=1e-16)


@given(st.lists(st.floats(0.0, 0.08), min_size=2, max_size=8))
def test_df_monotone_when_forwards_nonnegative(raw: list[float]) -> None:
    # SYNTHETIC: nondecreasing nonnegative zeros => d(z t)/dt >= 0 => forwards >= 0.
    zeros = tuple(sorted(raw))
    c = ZeroCurve("X", tuple(float(i + 1) for i in range(len(zeros))), zeros)
    dfs = np.asarray(c.df(np.linspace(0.0, len(zeros) + 2.0, 300)))
    assert np.all(np.diff(dfs) <= 1e-15)
