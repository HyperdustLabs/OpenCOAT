"""Temperature schedule tests for MAN slow rewrites."""

from __future__ import annotations

from opencoat_runtime_core.credit.temperature_schedule import TemperatureSchedule


def test_constant_temperature_schedule() -> None:
    schedule = TemperatureSchedule(kind="constant", initial=0.7, final=0.1)
    assert schedule.at(0) == 0.7
    assert schedule.at(20) == 0.7


def test_exponential_temperature_schedule_cools_to_final() -> None:
    schedule = TemperatureSchedule(
        kind="exponential",
        initial=1.0,
        final=0.25,
        decay=0.5,
    )
    assert schedule.at(0) == 1.0
    assert schedule.at(1) == 0.5
    assert schedule.at(3) == 0.25


def test_linear_temperature_schedule_interpolates() -> None:
    schedule = TemperatureSchedule(kind="linear", initial=1.0, final=0.2, steps=4)
    assert schedule.at(0) == 1.0
    assert schedule.at(2) == 0.6
    assert schedule.at(8) == 0.2
