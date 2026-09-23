"""
Surface finish: the outside of a printed object is not a flat face.

WHY THIS EXISTS
---------------
Every template in the catalogue was making correct geometry with a bare
outside. Correct and plain is the difference between a part somebody prints
and a part somebody keeps, and it is most of what people mean when they say a
downloaded model "looks better" - the downloaded one has flutes, or a
honeycomb, or a ribbed band, and whittle's had four flat faces.

`enclosure` already had a finish (`board`, `slat`) and it was written into
that one template. This is the same idea taken out to where anything can
reach it, with the same pitch / groove / depth vocabulary and the same
validators, so a container, a pot, a vase and a birdhouse all describe their
outside the same way.

WHAT IT PROMISES
----------------
1. IT NEVER GROWS THE PART. Every finish is cut, never added. The outside
   dimension a person asked for stays the outside dimension, so nominal_mm
   stays true and a part that fitted the drawer still fits it.
2. IT NEVER OPENS THE WALL. The depth is checked against the wall before a
   single cutter is built - a decoration that reaches the cavity is a hole.
3. IT PRINTS. Every family here is either vertical (a vertical groove has
   vertical flanks and no ceiling at all) or drafted, and the horizontal
   family ramps back out to the wall at 30 degrees off vertical the way
   `enclosure.board` does. That ramp is not decoration - square-cut rings put
   thousands of square millimetres of flat ceiling on a box.
4. IT FOLLOWS A TAPER. A cone's wall leans, so the cutters lean with it by
   the same angle. A vertical cutter on a tapered pot cuts through the rim
   and barely scratches the foot.

THE FAMILIES
------------
  plain   nothing.
  ribs    vertical square-cut grooves. The material left between them is the
          rib. Round or square bodies, and the safest thing to print.
  flutes  vertical round-bottomed grooves - classical fluting. Round bottoms
          because a square groove in a curved wall shows every layer seam at
          the corner.
  facets  flats cut around a round body: the low-poly look, and it makes a
          cylinder printable-looking without any pattern at all.
  hex     a staggered honeycomb of shallow drafted pockets.
  knurl   a staggered diamond of shallow drafted pockets - grip, not
          decoration, which is why it goes on lids and knobs.
  waves   horizontal rings, each ramped back out to the wall above it.

WHY THE POCKETS ARE DRAFTED AND NOT PRISMS
-------------------------------------------
A prismatic pocket cut straight into a wall has a flat ceiling at its top. A
honeycomb of them is a few hundred small ceilings. Lofting each pocket from a
smaller shape at its floor to the full shape at the surface makes every one of
those ceilings a slope instead, and costs nothing. The pockets are also
capped shallow for the same reason: past about a millimetre the slope is no
longer short enough to bridge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import cadquery as cq
from pydantic import BaseModel, Field as PydanticField

from whittle.build.helpers import BuildLog, compound_of

#: The names a finish can have. `plain` is a finish, not the absence of one -
#: a template that offers this list must be able to say "no pattern" in the
#: same field it says "honeycomb" in, or the English route to turning it off
#: does not exist (rule 32).
FINISHES = ("plain", "ribs", "flutes", "facets", "hex", "knurl", "waves")

#: Which families are patterns of small pockets rather than long grooves.
CELL_FINISHES = ("hex", "knurl")

#: Which families need the wall to run STRAIGHT from one end of the band to
#: the other.
#:
#: A rib is one long cutter and a facet is one long flat, and neither can
#: follow a silhouette that bends: on a bellied vase a straight rib cuts
#: through the waist and misses the shoulder entirely. The families that place
#: one small cutter at a time - the pockets and the rings - take the local
#: radius and the local lean at every row, so they follow any shape.
STRAIGHT_RUN_FINISHES = ("ribs", "flutes", "facets")

#: The deepest a derived finish goes, whatever the wall would allow. Past
#: this a pattern stops reading as a surface and starts reading as a hole.
DEFAULT_DEPTH_MM = 0.7

#: How far a silhouette may wander off the straight line between its ends
#: before it counts as curved. Half a millimetre is smaller than any cut this
#: module makes, so below it the difference cannot show.
CURVE_TOLERANCE_MM = 0.5

#: How far a horizontal groove climbs while it returns to the wall face, as a
#: multiple of its depth. 1.0 is exactly 45 degrees, which the overhang check
#: counts as a failure and not a pass. 1.7 is 30 degrees off vertical.
#:
#: The same number `enclosure` uses, for the same measured reason.
RAMP_RISE = 1.7

#: The deepest a drafted pocket is allowed to be, whatever the wall permits.
#:
#: This is not a wall-strength limit - it is a bridging one. The ceiling of a
#: drafted pocket is a short slope, and short is what makes it print. Past
#: about a millimetre the slope is long enough to droop, and a honeycomb of
#: drooped ceilings is what a bad surface finish looks like.
CELL_MAX_DEPTH_MM = 1.0

#: How much smaller a pocket is at its floor than at the surface. This is what
#: turns each ceiling into a slope. 0.55 at a 0.8 mm depth puts the pocket
#: wall at about 20 degrees off vertical.
CELL_DRAFT = 0.55

#: How tall a honeycomb cell is relative to its width.
#:
#: A REGULAR hexagon is the wrong shape here and it took a drawing to see why:
#: point-up, its upper edges are 30 degrees off HORIZONTAL, which is the worst
#: overhang of any polygon you could have picked. Stretched, those edges stand
#: up. 1.6 puts them at 51 degrees off horizontal, and the draft takes the
#: ceiling the rest of the way.
HEX_STRETCH = 1.6

#: The same, for a diamond knurl. Steeper again because a diamond has no flats
#: to hide behind.
KNURL_STRETCH = 1.8

#: Cutters past this count are not built. A honeycomb over a tall cylinder can
#: ask for two thousand pockets, which is not a finish, it is a way to make a
#: build take four minutes. The pitch is opened up until the count fits and
#: the change is reported - silently making a coarser pattern than was asked
#: for is exactly the sort of quiet substitution rule 9 forbids.
MAX_CUTTERS = 420


#: What people say for each finish. Declared ONCE and shared, because the
#: words are the interface (rule 32) and a template that spelt "honeycomb"
#: differently from its neighbour would be a capability that exists on one
#: object and not the next.
FINISH_SAYS: dict[str, list[str]] = {
    "plain": ["plain", "smooth", "flat", "flat sided", "no pattern",
              "undecorated"],
    "ribs": ["ribs", "ribbed", "ribbing", "vertical ribs", "grooved",
             "grooves", "lined", "striped", "corrugated"],
    "flutes": ["flutes", "fluted", "fluting", "scalloped", "classical",
               "column", "reeded"],
    "facets": ["facets", "faceted", "low poly", "low-poly", "polygonal",
               "prism", "geometric", "crystal"],
    "hex": ["hex", "hexagon", "hexagons", "hexagonal", "honeycomb",
            "honey comb", "cells", "beehive"],
    "knurl": ["knurl", "knurled", "knurling", "diamond", "diamonds",
              "cross hatch", "crosshatch", "grip", "gripped", "textured"],
    "waves": ["waves", "wave", "wavy", "ripple", "rippled", "ripples",
              "rings", "ridged", "ridges", "horizontal lines", "banded",
              "terraced"],
}


class Finished(BaseModel):
    """
    The four parameters a finish needs, for any template that has an outside.

    A MIXIN AND NOT FOUR COPIES. These started as four fields written into
    `enclosure`, and the second template to want them copied them. Copies
    drift: the day one of them gains a family the others do not, "put a
    honeycomb on it" works on a box and does nothing on a tray, and the
    person typing it has no way to know which.

        class TrayParams(surface.Finished, TemplateParams):
            ...

    The template still decides WHERE the finish goes - which band of which
    wall - because only the template knows that. This is what it is, not
    where.
    """

    finish: Literal["plain", "ribs", "flutes", "facets", "hex", "knurl",
                    "waves"] = PydanticField(
        "plain",
        json_schema_extra={"says": FINISH_SAYS},
        description=(
            "The pattern on the outside. plain is flat faces, which is most "
            "of why a downloaded model looks better than a generated one. "
            "ribs and flutes are vertical grooves; facets cut flats round a "
            "cylinder; hex and knurl are shallow pockets; waves are "
            "horizontal rings."
        ),
    )
    finish_pitch_mm: float = PydanticField(
        9.0, gt=1.0, le=60.0, description="Centre to centre of the pattern.",
    )
    finish_groove_mm: float = PydanticField(
        3.0, gt=0.4, le=40.0, description="How wide each cut, or each cell, is.",
    )
    finish_depth_mm: float | None = PydanticField(
        None, gt=0.1, le=4.0,
        description=(
            "How far into the wall. Left out, whichever is smaller of 0.7 mm "
            "and a third of the wall - a decoration that takes more than a "
            "third of the wall is a weakness, and one that reaches the cavity "
            "is a hole. Given explicitly it is checked, not clamped."
        ),
    )

    def finish_spec(self, wall_mm: float) -> "Finish":
        """
        The finish, with the depth worked out from the wall if nobody said.

        THE DEPTH HAS TO KNOW THE WALL. A fixed default is wrong on every
        template with a different wall: 0.7 mm is a quarter of a 2.8 mm box
        wall and more than a third of a 2.0 mm tray wall, so "a ribbed tray"
        was refused over five hundredths of a millimetre. Left out it is
        derived; written down it is checked and refused, because a number
        somebody typed is a number they meant.
        """
        # ROUNDED DOWN, not to nearest. A third of a 2.0 mm wall is 0.6667,
        # and 0.67 is over the limit it was derived from - so the number this
        # module works out for itself failed its own check, by five
        # thousandths of a millimetre.
        depth = (self.finish_depth_mm if self.finish_depth_mm is not None
                 else math.floor(min(DEFAULT_DEPTH_MM, wall_mm / 3.0) * 100) / 100)
        return Finish(self.finish, self.finish_pitch_mm,
                      self.finish_groove_mm, depth)


class SurfaceError(ValueError):
    """A finish that cannot be cut into this wall. Carries the legal figure."""


def _sample(profile: tuple[tuple[float, float], ...], z: float) -> float:
    """The silhouette's width at height z, straight-line between samples."""
    if z <= profile[0][0]:
        return profile[0][1]
    if z >= profile[-1][0]:
        return profile[-1][1]
    for (z0, w0), (z1, w1) in zip(profile, profile[1:]):
        if z0 <= z <= z1:
            if z1 - z0 < 1e-9:
                return w1
            return w0 + (w1 - w0) * (z - z0) / (z1 - z0)
    return profile[-1][1]


@dataclass
class Shell:
    """
    The outside of the thing being decorated, and nothing else about it.

    `bottom` and `top` are the OUTSIDE size at z0 and z1: (width, depth) for a
    square body, (diameter, diameter) for a round one. Giving both ends is
    what lets a taper be followed rather than ignored.
    """

    kind: str                       # "round" | "square"
    z0: float
    z1: float
    bottom: tuple[float, float]
    top: tuple[float, float]
    corner_r_mm: float = 0.0

    #: The silhouette as (height, width) samples, ascending in height, when
    #: the wall is not a straight run between `bottom` and `top`.
    #:
    #: A revolved vessel is the reason this exists: its wall is a curve, and
    #: interpolating between the two ends of that curve puts the wall up to
    #: several millimetres away from where it is. Everything that places one
    #: cutter at a time reads the real radius here instead.
    profile: tuple[tuple[float, float], ...] | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("round", "square"):
            raise SurfaceError("shell kind %r is not round or square" % self.kind)
        if self.z1 <= self.z0:
            raise SurfaceError(
                "the finish band runs from %.2f to %.2f, which is nothing"
                % (self.z0, self.z1)
            )

    @property
    def height(self) -> float:
        return self.z1 - self.z0

    def size_at(self, z: float) -> tuple[float, float]:
        """Outside (width, depth) at height z, off the silhouette."""
        if self.profile:
            w = _sample(self.profile, z)
            return (w, w)
        t = 0.0 if self.height <= 0 else (z - self.z0) / self.height
        return (self.bottom[0] + t * (self.top[0] - self.bottom[0]),
                self.bottom[1] + t * (self.top[1] - self.bottom[1]))

    @property
    def curved(self) -> bool:
        """
        Whether the wall bends between the two ends of the band.

        Measured against the silhouette rather than taken on trust: a caller
        that passes a profile for a straight-sided pot should still get the
        ribs it asked for.
        """
        if not self.profile:
            return False
        for z, w in self.profile:
            if not (self.z0 - 1e-9 <= z <= self.z1 + 1e-9):
                continue
            t = 0.0 if self.height <= 0 else (z - self.z0) / self.height
            straight = self.bottom[0] + t * (self.top[0] - self.bottom[0])
            if abs(w - straight) / 2.0 > CURVE_TOLERANCE_MM:
                return True
        return False

    def slope_at(self, z: float) -> float:
        """
        How far the wall leans out as it rises, in degrees, AT THIS HEIGHT.

        On a straight wall this is the same everywhere and `slope_deg` says
        so. On a curve it is not, and a cutter placed at the average lean
        stands off the wall at both ends.
        """
        if not self.profile:
            return self.slope_deg(0)
        step = max(0.25, self.height / 200.0)
        lo = _sample(self.profile, z - step)
        hi = _sample(self.profile, z + step)
        return math.degrees(math.atan2((hi - lo) / 2.0, 2 * step))

    def slope_deg(self, axis: int) -> float:
        """
        How far the wall leans out as it rises, in degrees, on one axis.

        Positive means the body widens upward - a plant pot. Negative means it
        narrows - a tumbler.
        """
        half = (self.top[axis] - self.bottom[axis]) / 2.0
        return math.degrees(math.atan2(half, self.height))


@dataclass
class Finish:
    """
    The pattern, in the same three numbers `enclosure` has always used.

    pitch is centre to centre, groove is how wide the cut is, depth is how far
    into the wall it goes. A cell pattern reads `groove` as the cell's width
    and `pitch` as the spacing, which is why a honeycomb with pitch equal to
    groove is a wall made of holes and is refused.
    """

    kind: str = "plain"
    pitch_mm: float = 9.0
    groove_mm: float = 3.0
    depth_mm: float = 0.8
    #: Kept so a template can record what it asked for even after a clamp.
    notes: list[str] = field(default_factory=list)


def check(f: Finish, wall_mm: float, shell: "Shell | None" = None) -> str | None:
    """
    Whether this finish can be cut into this wall.

    Returns the reason it cannot, WITH THE NUMBER THAT WOULD WORK, or None.
    Templates call this from their validator so the refusal arrives before
    anything is built and reads as a sentence rather than an OCC failure.

    The shell is optional because a validator usually runs before the body
    has been worked out. Pass it when it is known and the body-shape rules
    get checked too.
    """
    if f.kind == "plain":
        return None
    if f.kind not in FINISHES:
        return ("%r is not a surface finish. Available: %s."
                % (f.kind, ", ".join(FINISHES)))

    if f.kind in STRAIGHT_RUN_FINISHES and shell is not None and shell.curved:
        return ("%s runs the whole height as one cut, so it needs a wall that "
                "runs straight - this one bends. On a curved silhouette the "
                "rib cuts through the waist and misses the shoulder. What "
                "does follow a curve: hex, knurl and waves."
                % f.kind)

    if f.kind == "facets" and shell is not None and shell.kind != "round":
        return ("facets are flats cut around a ROUND body - they are what "
                "turns a cylinder into a prism. A square body already has "
                "flats. Try ribs, hex or waves.")

    # A groove deeper than a third of the wall is not a finish, it is a
    # weakness - and past half the wall it is a hole.
    limit = wall_mm / 3.0
    # A HAIR OF TOLERANCE, because a third of 1.2 is not 0.4 in binary. The
    # derived depth for a 1.2 mm gridfinity wall rounds to exactly 0.40 and
    # was then refused for exceeding 0.39999999999999997 - a limit this
    # module had just worked out for itself.
    if f.depth_mm > limit + 1e-9:
        return ("a %.2f mm deep %s in a %.2f mm wall takes more than a third "
                "of it. Legal: depth up to %.2f mm, or a thicker wall."
                % (f.depth_mm, f.kind, wall_mm, limit))

    if f.groove_mm >= f.pitch_mm:
        return ("the cuts are %.2f mm wide at %.2f mm spacing, so there is no "
                "wall left between them. Groove under %.2f mm."
                % (f.groove_mm, f.pitch_mm, f.pitch_mm))

    if f.kind in CELL_FINISHES and f.depth_mm > CELL_MAX_DEPTH_MM:
        return ("a %s pocket %.2f mm deep has a ceiling too long to bridge. "
                "Legal: up to %.2f mm - a pattern is shallow by nature."
                % (f.kind, f.depth_mm, CELL_MAX_DEPTH_MM))

    if f.kind in CELL_FINISHES and f.pitch_mm < f.groove_mm * 1.2:
        return ("%s cells %.2f mm wide need at least %.2f mm spacing or the "
                "wall between them is thinner than one extrusion."
                % (f.kind, f.groove_mm, f.groove_mm * 1.2))

    if f.kind == "waves":
        # A ring is its groove PLUS the ramp that climbs back out of it. Two
        # rings that overlap are not a deeper pattern, they are two cutters
        # sharing space, and a compound of overlapping cutters is undefined -
        # OCC is entitled to return a solid of negative volume, and does.
        ring = f.groove_mm + f.depth_mm * RAMP_RISE
        if ring >= f.pitch_mm:
            return ("each wave is %.2f mm tall once the ramp out of it is "
                    "counted, so at %.2f mm spacing they run into one "
                    "another. Spacing over %.2f mm, or a shallower cut."
                    % (ring, f.pitch_mm, ring))

    return None


# ---------------------------------------------------------------------------
# cutter shapes, built in a LOCAL frame:
#     +X is outward, away from the axis, with the wall surface at X = 0
#     +Y runs along the wall, sideways
#     +Z runs up the wall
# so every builder below can ignore where on the body it is going to land.
# ---------------------------------------------------------------------------

def _ramp_out(cutter: cq.Workplane, depth: float, length: float,
              groove: float) -> cq.Workplane:
    """
    Take the top off a vertical cutter so the groove climbs back out to the
    wall instead of stopping against a ceiling.

    A VERTICAL GROOVE HAS NO CEILING ANYWHERE EXCEPT AT ITS TOP END, and that
    end is easy to forget because the flanks are the part you think about. A
    groove that stops below the rim ends in a flat roof of groove x depth, and
    forty of them is 87 mm2 of unsupported plastic that the overhang check
    refuses outright - measured on a 120 x 90 box.

    So the cutter loses a wedge: everything deeper than the line that runs
    from full depth up to the wall face over RAMP_RISE times the depth. What
    is left ramps out at 30 degrees off vertical, which prints.

    The bottom end needs nothing. It faces up.
    """
    reach = depth * 4.0
    top = length / 2.0
    wedge = (
        cq.Workplane("XZ")
        .polyline([(0.0, top + reach),
                   (0.0, top),
                   (-reach, top - reach * RAMP_RISE),
                   (-reach, top + reach)])
        .close()
        .extrude(groove * 4.0, both=True)
    )
    return cutter.cut(wedge)


def _groove_square(groove: float, depth: float, length: float) -> cq.Workplane:
    """A square-cut vertical groove, ramped out at the top."""
    return _ramp_out(cq.Workplane("XY").box(2 * depth, groove, length),
                     depth, length, groove)


def _groove_round(groove: float, depth: float, length: float) -> cq.Workplane:
    """
    A round-bottomed vertical groove of exactly `groove` width at the surface.

    The radius is the circle through both rim points and the bottom of the
    cut, which is arithmetic rather than a guess: for half-width a and depth
    h, r = (a^2 + h^2) / 2h.
    """
    a = groove / 2.0
    r = (a * a + depth * depth) / (2.0 * depth)
    return _ramp_out(cq.Workplane("XY").cylinder(length, r)
                     .translate((r - depth, 0, 0)),
                     depth, length, groove)


def _facet_cutter(shell: Shell, f: Finish) -> cq.Workplane:
    """
    Facets, as ONE cutter: a slab over the band with the faceted prism taken
    out of it.

    The obvious way - a big box outside each flat, N of them - is wrong, and
    wrong in a way that passes isValid(). Those boxes OVERLAP each other
    heavily, and a compound of overlapping solids is not a defined thing to
    subtract: the measured result was a body of NEGATIVE volume. Unioning
    them instead works and is slow. The prism is exact, is one loft, and is
    what a faceted body actually is.

    The polygon is sized by its INRADIUS, because the flat is what the depth
    was measured to. Sizing by the circumradius leaves the flats `depth` too
    shallow and the corners untouched.
    """
    count = max(5, int(round(math.pi * shell.size_at(
        (shell.z0 + shell.z1) / 2.0)[0] / f.pitch_mm)))

    def ring(z: float, depth: float | None = None) -> list[tuple[float, float]]:
        inradius = shell.size_at(z)[0] / 2.0 - (
            f.depth_mm if depth is None else depth)
        circum = inradius / math.cos(math.pi / count)
        return [(circum * math.cos(2 * math.pi * i / count),
                 circum * math.sin(2 * math.pi * i / count))
                for i in range(count)]

    # THE BAND RAMPS BACK TO THE FULL SECTION AT THE TOP. Without it the
    # faceted part of the body ends in a step, and the underside of that step
    # is a ring of flat ceiling all the way round - 198 mm2, measured, on a
    # 100 mm tub. Over the last RAMP_RISE x depth of the band the polygon
    # grows until its flats touch the original surface, so the step becomes a
    # slope at 30 degrees off vertical.
    ramp = f.depth_mm * RAMP_RISE
    z_ramp = max(shell.z0 + 0.5, shell.z1 - ramp)

    prism = (
        cq.Workplane("XY", origin=(0, 0, shell.z0))
        .polyline(ring(shell.z0)).close()
        .workplane(offset=z_ramp - shell.z0)
        .polyline(ring(z_ramp)).close()
        .loft()
    )
    prism = prism.union(
        cq.Workplane("XY", origin=(0, 0, z_ramp))
        .polyline(ring(z_ramp)).close()
        .workplane(offset=shell.z1 - z_ramp)
        .polyline(ring(shell.z1, depth=0.0)).close()
        .loft()
    )
    reach = max(shell.bottom[0], shell.top[0]) * 2.0 + 20.0
    slab = (cq.Workplane("XY")
            .box(reach, reach, shell.height, centered=(True, True, False))
            .translate((0, 0, shell.z0)))
    return slab.cut(prism)


def _cell(profile: list[tuple[float, float]], depth: float) -> cq.Workplane:
    """
    One drafted pocket, lofted from a smaller shape at its floor to the full
    shape at the surface, so its ceiling is a slope and not a flat.

    The profile is given in (sideways, up) and the loft runs outward, ending
    1 mm PROUD of the surface. Ending exactly on the surface leaves a
    zero-thickness face where the cutter and the wall are coincident, and OCC
    is entitled to do anything at all with that.
    """
    inner = [(u * CELL_DRAFT, v * CELL_DRAFT) for u, v in profile]
    return (
        cq.Workplane("YZ", origin=(-depth, 0, 0))
        .polyline(inner).close()
        .workplane(offset=depth + 1.0)
        .polyline(profile).close()
        .loft()
    )


def _hex_profile(width: float) -> list[tuple[float, float]]:
    """A hexagon standing on a point, stretched upright so it can print."""
    a = width / 2.0
    b = a * HEX_STRETCH
    return [(0.0, b), (a, b / 2.0), (a, -b / 2.0),
            (0.0, -b), (-a, -b / 2.0), (-a, b / 2.0)]


def _diamond_profile(width: float) -> list[tuple[float, float]]:
    """A diamond standing on a point. Steeper than the hexagon: no flats."""
    a = width / 2.0
    b = a * KNURL_STRETCH
    return [(0.0, b), (a, 0.0), (0.0, -b), (-a, 0.0)]


def _place(cutter: cq.Workplane, theta_deg: float, radius: float,
           z: float, slope_deg: float) -> cq.Workplane:
    """
    Put a cutter built in the local frame onto the wall.

    The lean comes first, about +Y, which tips local +Z toward local +X - the
    direction a widening wall goes. Then out to the wall, then round to the
    face. Doing the lean after the move would swing the cutter round the axis
    of the whole body instead of tilting it against the wall, which is the
    kind of mistake that looks almost right in a render and is 4 mm out.
    """
    out = cutter
    if abs(slope_deg) > 0.01:
        out = out.rotate((0, 0, 0), (0, 1, 0), slope_deg)
    out = out.translate((radius, 0, z))
    if abs(theta_deg) > 0.01:
        out = out.rotate((0, 0, 0), (0, 0, 1), theta_deg)
    return out


# ---------------------------------------------------------------------------
# where the cutters go
# ---------------------------------------------------------------------------

@dataclass
class _Station:
    """One place on the wall a cutter can sit."""

    theta_deg: float
    radius: float          # distance from the axis to the wall, at z_mid
    offset: float          # sideways along the wall from the face centre
    slope_deg: float
    span: float            # how much wall is usable sideways at this station


def _faces(shell: Shell, z_mid: float) -> list[_Station]:
    """
    The flat faces of the body, as four stations - or for a round body, the
    single station whose `span` is the circumference.

    A square body is four separate walls and a groove on the front is not the
    same solid as a groove on the side at any rotation, which is why they are
    enumerated rather than patterned round.
    """
    w, d = shell.size_at(z_mid)
    if shell.kind == "round":
        r = w / 2.0
        return [_Station(0.0, r, 0.0, shell.slope_at(z_mid), 2 * math.pi * r)]
    return [
        _Station(0.0, w / 2.0, 0.0, shell.slope_deg(0), d),
        _Station(90.0, d / 2.0, 0.0, shell.slope_deg(1), w),
        _Station(180.0, w / 2.0, 0.0, shell.slope_deg(0), d),
        _Station(270.0, d / 2.0, 0.0, shell.slope_deg(1), w),
    ]


def _columns(shell: Shell, station: _Station, pitch: float, clear: float,
             stagger: bool) -> list[float]:
    """
    Where the columns of a pattern fall across one face, as a rotation for a
    round body and a sideways offset for a flat one.

    Centred on the face and working outward, so the pattern is symmetric
    however many fit. Starting at one edge and running out of room at the
    other looks like a mistake rather than a decision.
    """
    if shell.kind == "round":
        count = max(4, int(round(station.span / pitch)))
        step = 360.0 / count
        base = step / 2.0 if stagger else 0.0
        return [base + step * i for i in range(count)]

    usable = station.span - 2 * (shell.corner_r_mm + clear)
    if usable <= 0:
        return []
    count = int(usable // pitch)
    if count < 1:
        return []
    first = -count * pitch / 2.0 + (pitch / 2.0 if stagger else 0.0)
    span = [first + pitch * i for i in range(count + 1)]
    return [u for u in span if abs(u) <= usable / 2.0]


def _rows(shell: Shell, pitch: float, clear: float) -> list[float]:
    """Heights the rows of a cell pattern fall at, centred in the band."""
    usable = shell.height - 2 * clear
    if usable <= 0:
        return []
    count = int(usable // pitch)
    if count < 1:
        return []
    mid = (shell.z0 + shell.z1) / 2.0
    first = mid - count * pitch / 2.0
    return [first + pitch * i for i in range(count + 1)]


# ---------------------------------------------------------------------------
# the families
# ---------------------------------------------------------------------------

def _vertical_cutters(shell: Shell, f: Finish) -> list[cq.Workplane]:
    """ribs and flutes: one long cutter per column, leaning with the wall."""
    z_mid = (shell.z0 + shell.z1) / 2.0
    out: list[cq.Workplane] = []

    for station in _faces(shell, z_mid):
        # Along the slope, not along Z: a leaning wall is longer than the
        # height it covers, and a cutter cut to the height stops short of the
        # rim on a pot.
        length = shell.height / math.cos(math.radians(station.slope_deg)) + 2.0

        shape = (_groove_round if f.kind == "flutes" else _groove_square)(
            f.groove_mm, f.depth_mm, length)

        for u in _columns(shell, station, f.pitch_mm, f.groove_mm, stagger=False):
            if shell.kind == "round":
                out.append(_place(shape, u, station.radius, z_mid,
                                  station.slope_deg))
            else:
                out.append(_place(shape.translate((0, u, 0)), station.theta_deg,
                                  station.radius, z_mid, station.slope_deg))
    return out


def _cell_cutters(shell: Shell, f: Finish) -> list[cq.Workplane]:
    """hex and knurl: a staggered grid of shallow drafted pockets."""
    stretch = HEX_STRETCH if f.kind == "hex" else KNURL_STRETCH
    profile = (_hex_profile if f.kind == "hex" else _diamond_profile)(f.groove_mm)
    row_pitch = f.pitch_mm * stretch
    cell = _cell(profile, f.depth_mm)

    rows = _rows(shell, row_pitch, f.groove_mm * stretch)
    out: list[cq.Workplane] = []

    for i, z in enumerate(rows):
        stagger = bool(i % 2)
        for station in _faces(shell, z):
            for u in _columns(shell, station, f.pitch_mm, f.groove_mm, stagger):
                if shell.kind == "round":
                    out.append(_place(cell, u, station.radius, z,
                                      station.slope_deg))
                else:
                    out.append(_place(cell.translate((0, u, 0)),
                                      station.theta_deg, station.radius, z,
                                      station.slope_deg))
    return out


def _wave_cutters(shell: Shell, f: Finish) -> list[cq.Workplane]:
    """
    Horizontal rings, each ramped back out to the wall above it.

    THE RAMP IS THE WHOLE POINT. A square-cut ring leaves a flat ceiling all
    the way round the body, and forty of them is a surface made of ledges.
    Ending the ramp exactly ON the wall face - not outside it - is what keeps
    it at 30 degrees; `enclosure` learned that one the expensive way and the
    comment there has the measured numbers.
    """
    depth = f.depth_mm
    groove = f.groove_mm
    ramp = depth * RAMP_RISE
    out: list[cq.Workplane] = []

    z = shell.z0 + f.pitch_mm * 0.5
    while z + groove + ramp <= shell.z1 - f.pitch_mm * 0.25:
        if shell.kind == "round":
            r_low = shell.size_at(z)[0] / 2.0
            r_high = shell.size_at(z + groove + ramp)[0] / 2.0
            profile = [
                (r_low + 2.0, z),
                (r_low - depth, z),
                (r_low - depth, z + groove),
                (r_high, z + groove + ramp),
                (r_high + 2.0, z + groove + ramp),
            ]
            out.append(
                cq.Workplane("XZ").polyline(profile).close()
                .revolve(360, (0, 0, 0), (0, 1, 0))
            )
        else:
            w0, d0 = shell.size_at(z)
            w1, d1 = shell.size_at(z + groove + ramp)
            slab = (cq.Workplane("XY")
                    .box(w0 + 4.0, d0 + 4.0, groove + ramp, centered=(True, True, False))
                    .translate((0, 0, z)))
            # THE KEEP AND THE RAMP MUST MEET EXACTLY. Half a millimetre of
            # daylight between them and the cutter goes clean through the
            # wall, leaving the body as a stack of loose rings. It still
            # exports. It is still watertight.
            keep = (cq.Workplane("XY")
                    .box(w0 - 2 * depth, d0 - 2 * depth, groove + 0.5,
                         centered=(True, True, False))
                    .translate((0, 0, z - 0.5)))
            ramp_solid = (
                cq.Workplane("XY").workplane(offset=z + groove)
                .rect(w0 - 2 * depth, d0 - 2 * depth)
                .workplane(offset=ramp)
                .rect(w1, d1)
                .loft()
            )
            out.append(slab.cut(keep.union(ramp_solid)))
        z += f.pitch_mm
    return out


# ---------------------------------------------------------------------------
# the one thing a template calls
# ---------------------------------------------------------------------------

def apply(solid: cq.Workplane, shell: Shell, f: Finish,
          wall_mm: float, log: BuildLog | None = None) -> cq.Workplane:
    """
    Cut the finish into `solid` and hand it back.

    ONE BOOLEAN, NOT FOUR HUNDRED. The cutters are disjoint by construction,
    so they are compounded and subtracted in a single operation. Cutting them
    one at a time is the same answer and takes about forty times as long,
    which on a honeycomb is the difference between a build and a wait.

    A finish that cannot be cut raises rather than being quietly skipped. A
    pattern that silently did not happen is the worst outcome of the three:
    the part looks finished and is not what was asked for.
    """
    if f.kind == "plain":
        return solid

    bad = check(f, wall_mm, shell)
    if bad:
        raise SurfaceError(bad)

    spread = _resolve_pitch(shell, f, log)

    if spread.kind == "facets":
        cutters = [_facet_cutter(shell, spread)]
    elif spread.kind in ("ribs", "flutes"):
        cutters = _vertical_cutters(shell, spread)
    elif spread.kind in CELL_FINISHES:
        cutters = _cell_cutters(shell, spread)
    elif spread.kind == "waves":
        cutters = _wave_cutters(shell, spread)
    else:                                            # pragma: no cover
        raise SurfaceError("no cutter is written for %r" % spread.kind)

    if not cutters:
        raise SurfaceError(
            "a %s at %.1f mm spacing does not fit on a wall %.1f mm tall. "
            "Either a closer spacing or a taller body."
            % (f.kind, f.pitch_mm, shell.height)
        )

    if log is not None:
        log.notes.append(
            "the outside is %s: %d cuts at %.1f mm spacing, %.2f mm deep into "
            "a %.2f mm wall" % (spread.kind, len(cutters), spread.pitch_mm,
                                spread.depth_mm, wall_mm)
        )
        for note in spread.notes:
            log.notes.append(note)

    return solid.cut(compound_of(cutters))


def _resolve_pitch(shell: Shell, f: Finish, log: BuildLog | None) -> Finish:
    """
    Open the spacing up until the cutter count is something OCC can do in a
    reasonable time, and SAY SO when that happens.

    Estimated rather than built, because building four hundred pockets to
    discover there are four hundred of them defeats the purpose.
    """
    if f.kind not in CELL_FINISHES:
        return f

    stretch = HEX_STRETCH if f.kind == "hex" else KNURL_STRETCH
    w, d = shell.size_at((shell.z0 + shell.z1) / 2.0)
    perimeter = math.pi * w if shell.kind == "round" else 2 * (w + d)

    pitch = f.pitch_mm
    for _ in range(12):
        columns = max(1.0, perimeter / pitch)
        rows = max(1.0, shell.height / (pitch * stretch))
        if columns * rows <= MAX_CUTTERS:
            break
        pitch *= 1.25

    if pitch <= f.pitch_mm * 1.0001:
        return f

    out = Finish(kind=f.kind, pitch_mm=round(pitch, 2),
                 groove_mm=round(f.groove_mm * pitch / f.pitch_mm, 2),
                 depth_mm=f.depth_mm)
    out.notes.append(
        "the %s was opened from %.1f mm to %.1f mm spacing: at the size asked "
        "for it came to more than %d pockets, which is a four minute build "
        "rather than a finish"
        % (f.kind, f.pitch_mm, out.pitch_mm, MAX_CUTTERS)
    )
    return out
