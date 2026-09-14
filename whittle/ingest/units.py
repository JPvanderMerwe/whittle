"""
What the numbers in the file mean.

Build plan v8 section 5, step 2: "STL carries no units; infer from bounding
box, confirm with user."

WHY THIS IS A GUESS AND IS CALLED ONE
--------------------------------------
An STL is a list of coordinates with no statement anywhere of what they are.
The same file is a 40 mm bracket, a 4 cm bracket and a 0.04 m bracket, and
nothing in it distinguishes them. So this cannot be measured, only inferred,
and CLAUDE.md 29 is unambiguous about what whittle does with a value it cannot
measure: it says so rather than substituting a plausible number.

What makes the inference worth anything is that printed objects are not
uniformly distributed in size. They are almost all between a few millimetres
and the width of a print bed. A file whose longest side reads 0.086 is not an
86-micron object, it is 86 mm written in metres - because nobody prints an
86-micron anything.

So: score each candidate unit by how ordinary the resulting object would be,
return the best one, and return the runners-up with it. The caller shows the
user what was assumed and lets them change it. Nothing here scales anything.

GLTF IS NOT A GUESS. The glTF specification states that the unit is the metre.
That is the format's own contract rather than an inference from the numbers,
so it is reported as certain and the alternatives are not offered.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Millimetres per unit, for each candidate.
SCALES: dict[str, float] = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
}

#: The size range an object somebody prints actually falls in, in mm. The
#: floor is a few nozzle widths - below that there is nothing to print. The
#: ceiling is comfortably past the biggest common bed, so a genuinely large
#: model is not talked out of its own size.
PLAUSIBLE_MM = (3.0, 400.0)

#: Outside this it is not a printable object at all, at any unit.
CONCEIVABLE_MM = (0.5, 3000.0)


@dataclass
class UnitGuess:
    """What the file's numbers probably mean, and how sure that is."""

    units: str                      # mm, cm, m, in, or "unknown"
    scale_to_mm: float

    #: False only when the FORMAT states its units. True means this was
    #: inferred from the size of the thing, and the user should confirm it.
    assumed: bool

    #: Why this one. Written for a person: "0.086 across, which is 86 mm".
    reason: str

    #: The other readings that are not absurd, best first, as (units, size_mm).
    alternatives: list[tuple[str, float]] = field(default_factory=list)

    @property
    def certain(self) -> bool:
        return not self.assumed


def _plausibility(size_mm: float) -> float:
    """
    How ordinary an object of this size is, from 1.0 down to 0.0.

    Flat across the normal range rather than peaked at some "typical" size,
    because there is no typical size and pretending otherwise would make the
    guess prefer medium objects over small ones for no reason. Outside the
    range it falls away instead of stopping dead, so a 420 mm model is still
    a better reading than a 4.2 m one.
    """
    low, high = PLAUSIBLE_MM
    if low <= size_mm <= high:
        return 1.0
    floor, ceiling = CONCEIVABLE_MM
    if size_mm < low:
        if size_mm <= floor:
            return 0.0
        return (size_mm - floor) / (low - floor)
    if size_mm >= ceiling:
        return 0.0
    return (ceiling - size_mm) / (ceiling - high)


def guess_units(longest_mm_as_written: float,
                format_units: str | None = None) -> UnitGuess:
    """
    Read the file's own units where the format has them, otherwise infer.

    `longest_mm_as_written` is the longest side of the bounding box in
    whatever the file's numbers are - the raw figure, before any scaling.
    """
    if format_units:
        scale = SCALES[format_units]
        return UnitGuess(
            units=format_units,
            scale_to_mm=scale,
            assumed=False,
            reason="the format states its units are %s, so %.4g across is "
                   "%.4g mm" % (format_units, longest_mm_as_written,
                                longest_mm_as_written * scale),
        )

    if longest_mm_as_written <= 0:
        return UnitGuess(
            units="unknown", scale_to_mm=1.0, assumed=True,
            reason="the mesh has no size at all, so there is nothing to "
                   "infer units from",
        )

    scored = []
    for unit, scale in SCALES.items():
        size = longest_mm_as_written * scale
        scored.append((_plausibility(size), unit, size))
    # Best score first; on a tie prefer the smaller scale, which means mm over
    # cm over m. A 40-unit object is far more often 40 mm than 40 cm, and when
    # the scores cannot separate them the more common reading should win.
    scored.sort(key=lambda row: (-row[0], SCALES[row[1]]))

    best_score, best_unit, best_size = scored[0]
    if best_score <= 0.0:
        return UnitGuess(
            units="unknown", scale_to_mm=1.0, assumed=True,
            reason="%.4g across is not a printable object in any unit - "
                   "millimetres, centimetres, metres or inches all give "
                   "something impossible" % longest_mm_as_written,
            alternatives=[(u, s) for _, u, s in scored],
        )

    others = [(u, s) for score, u, s in scored[1:] if score > 0.0]
    return UnitGuess(
        units=best_unit,
        scale_to_mm=SCALES[best_unit],
        assumed=True,
        reason="%.4g across reads as %.4g mm, which is an ordinary size for "
               "something printed. Nothing in the file says so - check it."
               % (longest_mm_as_written, best_size),
        alternatives=others,
    )
