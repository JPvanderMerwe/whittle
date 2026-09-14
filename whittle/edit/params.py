"""
A parameter: a number the user can drag, with the bounds that keep it legal.

Build plan v8 section 10: "clamp slider ranges so most failures become
impossible rather than reported. A slider the user cannot drag into a broken
state beats an error message every time."

So bounds are not decoration. `wall_mm` on a 0.4 mm nozzle cannot go below
0.8 mm, because below that the operation produces something that cannot be
printed and the gate would immediately say so. Stopping the slider there means
the failure never happens instead of happening and being explained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Parameter:
    """One adjustable value on one operation."""

    name: str
    value: Any

    #: length | angle | count | bool | choice | axis
    kind: str = "length"
    units: str = "mm"
    low: float | None = None
    high: float | None = None
    step: float | None = None
    choices: tuple[str, ...] = ()
    description: str = ""

    #: Does changing this change whether the thing prints? The gate re-runs on
    #: every change to a parameter that does - v8 section 10 - and does not
    #: bother for the ones that cannot, like a rotation about the print axis.
    affects_print: bool = True

    @property
    def slidable(self) -> bool:
        """A slider needs both ends. Without them it is a number field."""
        return (self.kind in ("length", "angle", "count")
                and self.low is not None and self.high is not None
                and self.high > self.low)

    def clamp(self, value: Any) -> Any:
        """
        The nearest legal value to what was asked for.

        CLAMPED, NOT REFUSED. A slider dragged past its end should stop, not
        throw: the user is already looking at the model and an exception is
        not an answer to a gesture.
        """
        if self.kind == "bool":
            return bool(value)
        if self.kind in ("choice", "axis"):
            if self.choices and value not in self.choices:
                raise ValueError(
                    "%s must be one of %s, not %r"
                    % (self.name, ", ".join(self.choices), value))
            return value
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                "%s takes a number, not %r" % (self.name, value)) from None
        if self.low is not None:
            number = max(number, self.low)
        if self.high is not None:
            number = min(number, self.high)
        return int(round(number)) if self.kind == "count" else number

    def describe(self) -> str:
        if self.kind == "bool":
            return "%s %s" % (self.name, "on" if self.value else "off")
        if self.kind in ("choice", "axis"):
            return "%s %s" % (self.name, self.value)
        return "%s %g%s" % (self.name, float(self.value),
                            (" " + self.units) if self.units else "")


@dataclass
class ParameterSpec:
    """What a parameter looks like before it has a value: the schema for one."""

    name: str
    default: Any
    kind: str = "length"
    units: str = "mm"
    low: float | None = None
    high: float | None = None
    choices: tuple[str, ...] = ()
    description: str = ""
    affects_print: bool = True

    #: Bounds that depend on the machine or the model rather than being fixed.
    #: `wall_mm`'s floor is two nozzle widths, and the nozzle is not known when
    #: the schema is written. Given (nozzle_mm, extents_mm) it returns
    #: (low, high), either of which may be None to leave the fixed one.
    dynamic_bounds: Any = None

    def bind(self, value: Any = None, *, nozzle_mm: float = 0.4,
             extents_mm: tuple[float, float, float] | None = None) -> Parameter:
        """Make a live Parameter, with its bounds resolved for this model."""
        low, high = self.low, self.high
        if self.dynamic_bounds is not None:
            resolved_low, resolved_high = self.dynamic_bounds(
                nozzle_mm, extents_mm or (100.0, 100.0, 100.0))
            low = resolved_low if resolved_low is not None else low
            high = resolved_high if resolved_high is not None else high

        param = Parameter(
            name=self.name,
            value=self.default if value is None else value,
            kind=self.kind, units=self.units, low=low, high=high,
            choices=self.choices, description=self.description,
            affects_print=self.affects_print,
        )
        param.value = param.clamp(param.value)
        return param
