from __future__ import annotations

from math import sqrt
from statistics import StatisticsError


def _materialize_if_needed(values):
    """Return a reusable sized collection while keeping lists/tuples zero-copy."""
    if hasattr(values, "__len__") and hasattr(values, "__iter__"):
        return values
    return tuple(values)


def mean(values):
    """Fast arithmetic mean for the numeric float/int workloads used by Lottery AI.

    Unlike ``statistics.mean`` this intentionally avoids exact Fraction coercion.
    Generators are supported by materializing them once. Empty inputs preserve the
    standard-library ``StatisticsError`` contract.
    """
    xs = _materialize_if_needed(values)
    n = len(xs)
    if n == 0:
        raise StatisticsError("mean requires at least one data point")
    return sum(xs) / n


def pstdev(values, mu=None):
    """Fast population standard deviation matching the project's float use cases."""
    xs = _materialize_if_needed(values)
    n = len(xs)
    if n == 0:
        raise StatisticsError("pstdev requires at least one data point")
    centre = mean(xs) if mu is None else mu
    return sqrt(sum((x - centre) ** 2 for x in xs) / n)
