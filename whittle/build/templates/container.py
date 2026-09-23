"""
Container: the thing most people mean when they say "a box".

WHY ONE TEMPLATE AND NOT FIVE
-----------------------------
A lunch box, a parts tub, a jar with a screw-down lid, a stacking bin and a
desk pot are the same object with two things swapped: the SHAPE of the body
and the way the lid is HELD ON. Written as five templates they would be five
copies of the same wall-and-floor code, and the sixth request would find none
of them. Written as one, "a round tub with a clip-on lid" and "a tapered
square lunch box with magnets" are both reachable, and so are the fourteen
combinations nobody has asked for yet.

WHAT MAKES A CONTAINER GOOD, AND WHAT A BOX WITH A POCKET DOES NOT KNOW
-----------------------------------------------------------------------
  * THE LID HAS TO COME OFF AGAIN. A lid cut to the hole is a lid that is
    either welded in by the first layer's squish or falls off. Every mating
    surface here is cut back by the MATERIAL'S OWN measured clearance, which
    is a config figure, not a number chosen in this file.
  * A SNAP-FIT NEEDS SOMEWHERE TO FLEX. This is the one everybody gets wrong.
    A bead running right around a continuous skirt cannot deflect anywhere -
    the skirt is a closed loop and a closed loop is a hoop, so the lid either
    will not go on or it cracks. The bead goes on TABS, each one cut free of
    the skirt by a relief slot down each side, so it is a cantilever that can
    actually bend. That single difference is what separates a lid that clicks
    from a lid that splits.
  * A MAGNET NEEDS SOMEWHERE TO LIVE. A 6 mm magnet does not fit in a 2.4 mm
    wall. The wall is thickened into a rib at each magnet station - inward,
    so the outside is untouched - and the pocket goes down the top of that
    rib. The lid gets a thicker flange for the same reason rather than a
    bump on its face.
  * POCKETS OPEN UPWARD IN THE ORIENTATION THE PART PRINTS IN (rule 23). The
    body prints open side up, so its magnet pockets open up. The lid prints
    TOP FACE DOWN, so its pockets - which face down when the box is shut -
    also open up. Neither needs support and neither has a ceiling.
  * THE WALL IS THINNER ON A TAPER THAN IT LOOKS. Insetting a leaning wall by
    `wall` in plan gives a wall of `wall x cos(taper)` measured square to the
    face. At 10 degrees that is 1.5% and nobody would notice; it is divided
    out anyway, because a number that is nearly right is how tolerances get
    eaten.

WHERE A PRINTED CONTAINER FAILS
-------------------------------
  * the lid does not fit, because the clearance was guessed.
  * the snap-fit lid cracks on the third close, because the bead was on a
    hoop instead of a tab.
  * the outside is four flat faces, which is why the downloaded one looked
    better. Every body here can carry a surface finish - see whittle/build/
    surface.py - and the finish is cut, never added, so the box that fitted
    the drawer still fits it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cadquery as cq
from pydantic import Field, model_validator

from whittle.build import surface
from whittle.build.helpers import (
    BuildLog,
    compound_of,
    safe_fillet_radius,
    try_edge_op,
)
from whittle.spec.registry import Template, register
from whittle.spec.schema import TemplateParams

#: The lid's own height as a fraction of the body's, when nobody said.
LID_SKIRT_FRACTION = 0.18

#: The shortest skirt worth having. Below this the lid rocks on the rim and
#: lifts off the moment the box is picked up by it.
MIN_SKIRT_MM = 4.0

#: Material left over a magnet pocket. Less than this and the first layer over
#: the magnet is the only thing holding it in.
MAGNET_COVER_MM = 1.2

#: Material left around a magnet, radially.
MAGNET_SURROUND_MM = 1.2

#: How much bigger a magnet pocket is than the magnet. Magnets are sintered
#: and sold to a loose tolerance; a pocket cut to the nominal size needs a
#: hammer, and a hammer on a neodymium magnet produces two magnets.
MAGNET_POCKET_EASE_MM = 0.15

#: Snap bead height as a fraction of the skirt's thickness.
#:
#: ASSUMPTION, and flagged as one in the report. The honest engineering figure
#: is a beam deflection: a cantilever of thickness t and length L can take a
#: tip deflection of about strain x L^2 / (1.5 t), and PLA's usable strain is
#: around 1.5%. For the skirts this template builds - roughly 1.6 mm thick and
#: 12 mm long - that lands near 0.9 mm, and 0.35 x t = 0.56 mm sits inside it
#: with room for the tab being stiffer than an ideal beam at its root. It is
#: not measured, so it is named, defaulted and overridable.
SNAP_BEAD_FRACTION = 0.35
SNAP_BEAD_MAX_MM = 0.7

#: How far a flank climbs while it returns to the wall face, as a multiple of
#: its depth. 1.0 is exactly 45 degrees, which the overhang check counts as a
#: failure and not a pass; 1.7 is 30 degrees off vertical. Taken from the
#: surface module rather than written again, because it is the same number
#: for the same reason and two copies drift.
RAMP_RISE = surface.RAMP_RISE

#: Air above and below the bead inside its groove.
#:
#: Without it the bead's bottom edge and the groove's floor are the same
#: surface, which is not a fit, it is two faces OCC has to decide about - and
#: on a tapered body it is where the lid ends up inside the box.
SNAP_BEAD_MARGIN_MM = 0.3

#: The relief slot down each side of a snap tab. One nozzle width would close
#: up; this is two, so the slot survives being sliced.
SNAP_SLOT_MM = 1.2

#: How much of the skirt is left uncut at the top of a snap tab, so the tab
#: has a root to hinge about.
SNAP_ROOT_MM = 1.5

#: Depth of the stacking groove in the underside.
STACK_GROOVE_MM = 2.5


class ContainerParams(surface.Finished, TemplateParams):
    """Every dimension carries its unit in the name."""

    # --- the body ---------------------------------------------------------
    shape: Literal["square", "round"] = Field(
        "square",
        description=(
            "Square holds more in a drawer and stacks; round is stronger for "
            "the same wall and has no corners to clean out."
        ),
        json_schema_extra={"says": {
            "square": ["square", "rectangular", "rectangle", "oblong",
                       "box shaped", "box-shaped"],
            "round": ["round", "circular", "cylindrical", "cylinder", "tube",
                      "drum"],
        }},
    )
    width_mm: float = Field(
        120.0, gt=20.0, le=400.0,
        description=(
            "Outside, left to right, AT THE RIM - the widest point. Square "
            "bodies only. The rim is the number that decides whether it goes "
            "in the drawer."
        ),
    )
    depth_mm: float = Field(
        90.0, gt=20.0, le=400.0,
        description="Outside, front to back, at the rim. Square bodies only.",
    )
    diameter_mm: float = Field(
        100.0, gt=20.0, le=400.0,
        description="Outside across the rim. Round bodies only.",
    )
    height_mm: float = Field(
        70.0, gt=10.0, le=400.0, description="Outside, floor to rim.",
    )
    taper_deg: float = Field(
        0.0, ge=0.0, le=14.0,
        json_schema_extra={
            "says": ["taper", "tapered", "tapering", "sloped", "sloping",
                     "conical", "flared"],
            # What the bare adjective means with no figure beside it. 8
            # degrees is the angle a stack of takeaway tubs is drawn at:
            # enough that they nest, not so much that the base is a disc.
            "sets": {"tapered": 8.0, "tapering": 8.0, "nesting": 8.0,
                     "nest": 8.0, "conical": 10.0, "flared": 10.0,
                     "straight sided": 0.0, "straight-sided": 0.0},
        },
        description=(
            "How far the walls lean in going down. 0 is a straight tub. 6-10 "
            "degrees makes them nest inside one another when empty, which is "
            "what a stack of takeaway tubs is doing."
        ),
    )

    wall_mm: float = Field(
        2.4, ge=1.2, le=10.0,
        description="The side wall. 2.4 is two perimeters of a 0.6 nozzle.",
    )
    floor_mm: float | None = Field(
        None, ge=0.8, le=15.0,
        description=(
            "The floor. Left out, 1.4 x the wall - the floor is what gets set "
            "down on a table and what the contents press on."
        ),
    )
    corner_r_mm: float | None = Field(
        None, ge=0.0, le=60.0,
        description="Corner rounding on a square body. Left out, 3 x the wall.",
    )

    columns: int = Field(
        1, ge=1, le=6,
        json_schema_extra={"says": ["columns", "compartments", "divisions",
                                    "sections", "dividers", "divided"]},
        description=(
            "Compartments left to right. More than one makes it a lunch box "
            "rather than a tub. Square bodies only."
        ),
    )
    rows: int = Field(
        1, ge=1, le=6, description="Compartments front to back.",
    )

    # --- how it closes ----------------------------------------------------
    closure: Literal["open", "lid", "clip", "magnet", "hinge"] = Field(
        "lid",
        json_schema_extra={"says": {
            "open": ["open", "open top", "no lid", "without a lid",
                     "lidless", "tub", "bin", "pot"],
            "lid": ["lid", "with a lid", "lidded", "drop on lid",
                    "removable lid", "loose lid", "plain lid"],
            "clip": ["clip", "clips", "clip close", "clip-close", "clip on",
                     "clip-on", "snap", "snaps", "snap fit", "snap-fit",
                     "snap close", "click", "clicks shut", "latch",
                     "latching", "clips shut", "stays shut"],
            "magnet": ["magnet", "magnets", "magnetic", "magnetic lid",
                       "magnetically", "magnet closure"],
            "hinge": ["hinge", "hinged", "hinged lid", "flip top",
                      "flip-top", "flip lid", "swings open", "attached lid"],
        }},
        description=(
            "open: a tub, no lid. lid: a lid that drops into the mouth on a "
            "skirt. clip: the same lid with snap tabs that click over a "
            "groove - it stays shut upside down. magnet: held by magnets in "
            "the rim, which opens with one finger. hinge: knuckles at the "
            "back and a printed pin, so the lid cannot be put down and lost."
        ),
    )
    lid_skirt_mm: float | None = Field(
        None, ge=2.0, le=60.0,
        description=(
            "How far the lid's skirt reaches down inside. Left out, 18% of "
            "the height and never under 4 mm - a short skirt lets the lid "
            "rock and lift off."
        ),
    )
    lid_clearance_mm: float | None = Field(
        None, ge=0.05, le=1.0,
        description=(
            "The air between lid and body. Left out, the MATERIAL'S OWN "
            "measured clearance from config - a figure harvested from test "
            "prints, not chosen here."
        ),
    )

    magnet_dia_mm: float = Field(
        6.0, gt=2.0, le=25.0, description="Magnet diameter. 6 x 3 discs are the common size.",
    )
    magnet_thick_mm: float = Field(
        3.0, gt=0.8, le=15.0, description="Magnet thickness.",
    )
    magnet_count: int = Field(
        4, ge=2, le=12, description="How many pairs. Four is a lid that will not twist off.",
    )

    snap_tab_count: int = Field(
        2, ge=1, le=8,
        description=(
            "Snap tabs around the skirt. Two opposite each other is a lid you "
            "can pop with a thumb; four needs two hands."
        ),
    )
    snap_bead_mm: float | None = Field(
        None, ge=0.15, le=2.0,
        description=(
            "How far the snap bead stands proud. Left out, 35% of the skirt "
            "thickness - see SNAP_BEAD_FRACTION, which shows the deflection "
            "that figure came from. This is an ASSUMPTION and is reported."
        ),
    )

    pin_dia_mm: float = Field(
        3.0, gt=1.5, le=10.0,
        description="Hinge pin. Printed as a third body, or use a 3 mm rod.",
    )

    stackable: bool = Field(
        False,
        json_schema_extra={"says": ["stackable", "stacking", "stack",
                                    "stacks", "stackable set"]},
        description=(
            "A groove in the underside that sits over the rim - or over the "
            "lid's raised ring - of the one below, so a stack does not slide."
        ),
    )

    # --- the outside ------------------------------------------------------
    #
    # The four finish parameters come from surface.Finished, which every
    # template with an outside inherits. One definition, so "put a honeycomb
    # on it" means the same thing on a box as on a tray.

    @model_validator(mode="after")
    def _buildable(self) -> "ContainerParams":
        wall = self.wall_mm
        floor = self.floor_mm if self.floor_mm is not None else 1.4 * wall

        rim_w, rim_d = _rim_size(self)
        base_w, base_d = _base_size(self)
        if min(base_w, base_d) < 0.45 * min(rim_w, rim_d):
            raise ValueError(
                "a %.0f degree taper over %.0f mm leaves a base %.0f mm across "
                "under a %.0f mm rim - that is a funnel, not a container. Less "
                "taper or less height."
                % (self.taper_deg, self.height_mm, min(base_w, base_d),
                   min(rim_w, rim_d))
            )

        inset = _inset(self)
        if min(base_w, base_d) - 2 * inset < 12.0:
            raise ValueError(
                "a %.1f mm wall leaves only %.1f mm across the inside at the "
                "base. A thinner wall, a wider body, or less taper."
                % (wall, min(base_w, base_d) - 2 * inset)
            )
        if floor >= self.height_mm - 3.0:
            raise ValueError(
                "a %.1f mm floor in a %.1f mm tall body leaves no container."
                % (floor, self.height_mm)
            )

        if self.shape == "round" and (self.columns > 1 or self.rows > 1):
            raise ValueError(
                "compartments are a square-container thing - a grid of them in "
                "a round body leaves crescent-shaped corners nothing fits in. "
                "Either shape='square', or one space."
            )
        if self.shape == "square":
            inner_w = base_w - 2 * inset
            inner_d = base_d - 2 * inset
            cell_w = (inner_w - (self.columns - 1) * wall) / self.columns
            cell_d = (inner_d - (self.rows - 1) * wall) / self.rows
            if min(cell_w, cell_d) < 10.0:
                raise ValueError(
                    "%d x %d compartments in a body %.0f x %.0f leaves cells "
                    "%.1f x %.1f mm at the base - nothing fits in that."
                    % (self.columns, self.rows, base_w, base_d, cell_w, cell_d))

        if self.closure == "open" and self.lid_skirt_mm is not None:
            raise ValueError(
                "closure='open' is a tub with no lid, so a lid skirt has "
                "nothing to belong to. Either a closure with a lid, or drop "
                "lid_skirt_mm."
            )

        if self.closure == "magnet":
            need = self.magnet_dia_mm + 2 * MAGNET_SURROUND_MM
            inside = min(base_w, base_d) - 2 * inset
            # THE BOSS IS THE LIMIT, NOT THE MAGNET. The magnet sits in a rib
            # standing in from the wall, so what has to fit is how far that
            # rib reaches - and a rib eating a third of the width leaves a
            # container that is mostly rib.
            if need - wall > inside * 0.35:
                raise ValueError(
                    "a %.1f mm magnet needs a boss standing %.1f mm into a "
                    "container only %.1f mm across inside, which would leave "
                    "no container. A smaller magnet, or a wider body."
                    % (self.magnet_dia_mm, need - wall, inside))
            if need > inside:
                raise ValueError(
                    "a %.1f mm magnet needs a %.1f mm boss, which is wider "
                    "than the inside of this container."
                    % (self.magnet_dia_mm, need))
            if self.shape == "square" and self.magnet_count % 4:
                raise ValueError(
                    "magnets on a square body go one to a side, so the count "
                    "has to be a multiple of 4. 4 or 8.")

        if self.closure == "clip":
            skirt_t = max(1.2, 0.7 * wall)
            bead = (self.snap_bead_mm if self.snap_bead_mm is not None
                    else min(SNAP_BEAD_MAX_MM, SNAP_BEAD_FRACTION * skirt_t))
            if wall - (bead + 0.1) < 0.8:
                raise ValueError(
                    "a %.2f mm snap bead needs a %.2f mm groove in a %.2f mm "
                    "wall, leaving %.2f mm behind it. Thicker wall, or a "
                    "smaller bead."
                    % (bead, bead + 0.1, wall, wall - bead - 0.1))

        if self.stackable and floor < STACK_GROOVE_MM + 0.8:
            raise ValueError(
                "a stacking groove is %.1f mm deep and this floor is %.1f mm, "
                "so the groove would go through it. floor_mm of at least %.1f."
                % (STACK_GROOVE_MM, floor, STACK_GROOVE_MM + 0.8))

        bad = surface.check(self.finish_spec(wall), wall, _shell(self, floor))
        if bad:
            raise ValueError(bad)
        return self


# ---------------------------------------------------------------------------
# the body's plan, at any height
# ---------------------------------------------------------------------------

def _rim_size(p: ContainerParams) -> tuple[float, float]:
    if p.shape == "round":
        return (p.diameter_mm, p.diameter_mm)
    return (p.width_mm, p.depth_mm)


def _base_size(p: ContainerParams) -> tuple[float, float]:
    lost = 2.0 * math.tan(math.radians(p.taper_deg)) * p.height_mm
    w, d = _rim_size(p)
    return (w - lost, d - lost)


def _plan(p: ContainerParams, z: float) -> tuple[float, float]:
    """Outside (width, depth) at height z. The rim is the widest point."""
    lost = 2.0 * math.tan(math.radians(p.taper_deg)) * (p.height_mm - z)
    w, d = _rim_size(p)
    return (w - lost, d - lost)


def _inset(p: ContainerParams) -> float:
    """
    How far in from the outside the cavity is drawn, IN PLAN.

    Not `wall`. A leaning wall inset by `wall` in plan measures `wall x
    cos(taper)` square to its own face, so the inset is divided by that
    cosine. It is 1.5% at ten degrees and it is still wrong to leave in.
    """
    return p.wall_mm / math.cos(math.radians(p.taper_deg))


def _shell(p: ContainerParams, floor: float) -> surface.Shell:
    """The band of outside wall a finish is allowed to touch."""
    z0 = floor + 2.0
    z1 = max(z0 + 1.0, p.height_mm - 3.0)
    return surface.Shell(
        kind=p.shape, z0=z0, z1=z1,
        bottom=_plan(p, z0), top=_plan(p, z1),
        corner_r_mm=(p.corner_r_mm if p.corner_r_mm is not None
                     else 3.0 * p.wall_mm),
    )


def _prism(p: ContainerParams, w0: float, d0: float, w1: float, d1: float,
           r: float, z0: float, z1: float) -> cq.Workplane:
    """
    A solid running from (w0, d0) at z0 to (w1, d1) at z1.

    Straight sides are a box or a cylinder rather than a loft of two identical
    profiles: OCC will loft it, but a prism is exact, and every later boolean
    against it is faster and better behaved.
    """
    h = z1 - z0
    if p.shape == "round":
        if abs(w1 - w0) < 1e-6:
            return (cq.Workplane("XY", origin=(0, 0, z0))
                    .circle(w0 / 2.0).extrude(h))
        return (cq.Workplane("XY", origin=(0, 0, z0))
                .circle(w0 / 2.0)
                .workplane(offset=h).circle(w1 / 2.0).loft())

    r0 = max(0.0, min(r, min(w0, d0) / 2.0 - 0.2))
    r1 = max(0.0, min(r, min(w1, d1) / 2.0 - 0.2))
    if abs(w1 - w0) < 1e-6 and abs(d1 - d0) < 1e-6:
        solid = (cq.Workplane("XY", origin=(0, 0, z0))
                 .box(w0, d0, h, centered=(True, True, False)))
        if r0 > 0.3:
            solid = solid.edges("|Z").fillet(safe_fillet_radius(r0, w0, d0))
        return solid

    def sketch(w: float, d: float, rr: float) -> cq.Sketch:
        s = cq.Sketch().rect(w, d)
        return s.vertices().fillet(rr) if rr > 0.3 else s

    return (cq.Workplane("XY", origin=(0, 0, z0))
            .placeSketch(sketch(w0, d0, r0),
                         sketch(w1, d1, r1).moved(cq.Location(cq.Vector(0, 0, h))))
            .loft())


def _wall_prism(p: ContainerParams, z0: float, z1: float, shrink: float,
                r: float) -> cq.Workplane:
    """
    A prism that follows the outside of the body, inset by `shrink` a side,
    over exactly z0 to z1.

    THE PROFILE COMES FROM THE HEIGHT, and every tapered solid in this file
    goes through here for that reason. Passing the sizes in by hand is one
    line shorter and it is how three separate bugs got in: a cavity given the
    rim's size but extruded a millimetre past the rim, and a snap groove given
    its size at z0 and z1 but extruded a millimetre beyond both. In each case
    the same taper is stretched over a longer run, so the solid is slightly
    the wrong size ALL THE WAY DOWN.

    That error is two tenths of a millimetre. It is invisible, it is inside
    the wall tolerance everywhere - and it is four times the clearance holding
    the lid on, so it showed up as the lid being inside the box.

    A negative `shrink` grows the prism, which is how a groove's outer face is
    drawn: it is the wall face pushed outward by the depth of the cut.
    """
    w0, d0 = _plan(p, z0)
    w1, d1 = _plan(p, z1)
    return _prism(p, w0 - 2 * shrink, d0 - 2 * shrink,
                  w1 - 2 * shrink, d1 - 2 * shrink, r, z0, z1)


def _wall_loft(p: ContainerParams, z0: float, z1: float, shrink0: float,
               shrink1: float, r: float) -> cq.Workplane:
    """_wall_prism with a different inset at each end: a ramp in the wall."""
    w0, d0 = _plan(p, z0)
    w1, d1 = _plan(p, z1)
    return _prism(p, w0 - 2 * shrink0, d0 - 2 * shrink0,
                  w1 - 2 * shrink1, d1 - 2 * shrink1, r, z0, z1)


@dataclass
class _Derived:
    floor: float
    corner_r: float
    inset: float
    clearance: float
    skirt: float
    skirt_t: float
    lid_flange: float
    bead: float
    stations: list[float]      # angles, degrees, for magnets / snap tabs


def derive(p: ContainerParams, clearance_mm: float | None) -> _Derived:
    # THE MATERIAL'S OWN CLEARANCE. config carries a measured figure per
    # material; 0.30 is the fallback and only because a flexible filament's
    # clearance guessed here would be wrong in the direction that welds a lid
    # shut.
    clearance = p.lid_clearance_mm if p.lid_clearance_mm is not None else (
        clearance_mm if clearance_mm else 0.30)

    floor = p.floor_mm if p.floor_mm is not None else round(1.4 * p.wall_mm, 2)
    skirt = p.lid_skirt_mm if p.lid_skirt_mm is not None else max(
        MIN_SKIRT_MM, round(p.height_mm * LID_SKIRT_FRACTION, 1))
    skirt_t = max(1.2, round(0.7 * p.wall_mm, 2))
    bead = (p.snap_bead_mm if p.snap_bead_mm is not None
            else round(min(SNAP_BEAD_MAX_MM, SNAP_BEAD_FRACTION * skirt_t), 2))

    flange = floor
    if p.closure == "magnet":
        # The flange has to be deep enough to bury a magnet with cover over
        # it. A pad on the face instead would print as a ceiling.
        flange = max(floor, p.magnet_thick_mm + MAGNET_COVER_MM)

    count = p.magnet_count if p.closure == "magnet" else p.snap_tab_count
    if p.shape == "square":
        # ONE TO A SIDE, at the middle of the face. The corners are rounded
        # and a magnet in a corner is a magnet in the radius.
        stations = [90.0 * i for i in range(4)][:max(1, min(4, count))]
        if count > 4:
            stations = [90.0 * i + off for i in range(4) for off in (-20.0, 20.0)]
    else:
        stations = [360.0 * i / count for i in range(count)]

    return _Derived(
        floor=floor,
        corner_r=(p.corner_r_mm if p.corner_r_mm is not None
                  else round(3.0 * p.wall_mm, 2)),
        inset=_inset(p),
        clearance=clearance,
        skirt=skirt,
        skirt_t=skirt_t,
        lid_flange=flange,
        bead=bead,
        stations=stations,
    )


# ---------------------------------------------------------------------------
# the body
# ---------------------------------------------------------------------------

def _wall_normal(p: ContainerParams, theta_deg: float, z: float) -> float:
    """Distance from the axis out to the OUTSIDE wall, at this angle and height."""
    w, d = _plan(p, z)
    if p.shape == "round":
        return w / 2.0
    return (w / 2.0) if int(round(theta_deg)) % 180 == 0 else (d / 2.0)


def build_body(p: ContainerParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    rim_w, rim_d = _plan(p, p.height_mm)
    base_w, base_d = _plan(p, 0.0)

    solid = _wall_prism(p, 0.0, p.height_mm, 0.0, d.corner_r)

    # The cavity, drawn inset from the outside at BOTH ends so it follows the
    # taper rather than cutting through it near the rim.
    #
    # THE TOP PROFILE IS TAKEN AT THE HEIGHT THE PRISM ACTUALLY ENDS AT, which
    # is a millimetre above the rim so the pocket breaks the top face cleanly.
    # Taking it at the rim instead stretches the same taper over a longer run,
    # so the cavity comes out slightly small all the way down - 0.19 mm on an
    # 8 degree box. That is invisible, it is inside the wall tolerance
    # everywhere except one place, and that place is the snap groove, where it
    # left a lip the bead jammed on. Measured: 10.7 mm3 of lid inside the body.
    over = p.height_mm + 1.0
    cav_b = tuple(s - 2 * d.inset for s in _plan(p, d.floor))
    cav_t = (rim_w - 2 * d.inset, rim_d - 2 * d.inset)

    if p.shape == "square" and (p.columns > 1 or p.rows > 1):
        # EACH COMPARTMENT CUT SEPARATELY, so the material left between the
        # cuts IS the divider and can never end up floating - the same rule
        # the tray works to.
        solid = solid.cut(_compartments(p, d, cav_b, cav_t))
    else:
        cavity = _wall_prism(p, d.floor, over, d.inset,
                             max(0.0, d.corner_r - d.inset))
        solid = solid.cut(cavity)

    if p.closure == "clip":
        solid = solid.cut(_snap_groove(p, d))

    if p.closure == "magnet":
        solid = solid.union(_magnet_bosses(p, d))
        solid = solid.cut(_magnet_pockets(p, d, z_top=p.height_mm))

    if p.stackable:
        solid = solid.cut(_stack_groove(p, d))

    if p.closure == "hinge":
        solid = solid.union(_knuckles(p, d, which="body"))
        solid = solid.cut(_hinge_relief(p, d, which="body"))
        solid = solid.cut(_knuckle_bore(p, d))

    if p.finish != "plain":
        solid = surface.apply(solid, _shell(p, d.floor),
                              p.finish_spec(p.wall_mm), p.wall_mm, log)

    solid = try_edge_op(solid, ">Z", "chamfer", min(0.6, p.wall_mm * 0.3),
                        "rim break", log)
    return solid


def _compartments(p: ContainerParams, d: _Derived,
                  cav_b: tuple[float, float],
                  cav_t: tuple[float, float]) -> cq.Workplane:
    """
    The pockets, as one compound - they are disjoint, so one boolean does.

    EACH POCKET IS CUT SEPARATELY rather than hollowing the whole inside and
    adding dividers back, so the material left between the cuts IS the divider
    and can never end up floating or half a millimetre out of place. The tray
    works the same way.

    EACH END OF THE LOFT IS PLACED AT ITS OWN CENTRE. On a tapered body the
    cells at the rim are wider than the cells at the floor, so they are also
    at different centres - the outer ones move outward. Lofting between two
    differently sized rectangles and then moving the whole pocket by the
    BOTTOM centre leans every outer pocket the wrong way, and near the rim it
    leans far enough to eat the outside wall: a four degree taper with two
    compartments came out as five separate solids and an STL with holes in it.
    """
    def cell(size: tuple[float, float], col: int, row: int):
        inner_w, inner_d = size
        cw = (inner_w - (p.columns - 1) * p.wall_mm) / p.columns
        cd = (inner_d - (p.rows - 1) * p.wall_mm) / p.rows
        cx = -inner_w / 2.0 + col * (cw + p.wall_mm) + cw / 2.0
        cy = -inner_d / 2.0 + row * (cd + p.wall_mm) + cd / 2.0
        return cw, cd, cx, cy

    def face(w: float, dp: float, r: float) -> cq.Sketch:
        s = cq.Sketch().rect(w, dp)
        return s.vertices().fillet(r) if r > 0.3 else s

    cells = []
    for col in range(p.columns):
        for row in range(p.rows):
            bw, bd, bx, by = cell(cav_b, col, row)
            tw, td, tx, ty = cell(cav_t, col, row)
            r = max(0.0, min(d.corner_r - d.inset, min(bw, bd) / 2.0 - 0.3))
            pocket = (
                cq.Workplane("XY", origin=(0, 0, d.floor))
                .placeSketch(
                    face(bw, bd, r).moved(cq.Location(cq.Vector(bx, by, 0))),
                    face(tw, td, r).moved(
                        cq.Location(cq.Vector(tx, ty, p.height_mm - d.floor))),
                )
                .loft()
            )
            # Overshoot the rim so the pocket breaks the top face cleanly. At
            # the top size and the top centre, which is the same thing said
            # twice and was got wrong once.
            top = (cq.Workplane("XY", origin=(0, 0, p.height_mm - 0.01))
                   .rect(tw, td).extrude(2.0)
                   .translate((tx, ty, 0)))
            cells.append(pocket.union(top))
    return compound_of(cells)


def _stack_groove(p: ContainerParams, d: _Derived) -> cq.Workplane:
    """
    A groove in the underside that drops over the rim of the one below.

    It is a GROOVE, not a pocket: its outer edge follows the outside of the
    rim and its inner edge follows the inside, so the two sit on each other's
    wall and cannot slide. A full-width pocket would leave the stack resting
    on a knife edge.
    """
    rim_w, rim_d = _plan(p, p.height_mm)
    outer = _prism(p, rim_w + 2 * d.clearance, rim_d + 2 * d.clearance,
                   rim_w + 2 * d.clearance, rim_d + 2 * d.clearance,
                   d.corner_r, -0.5, STACK_GROOVE_MM)
    keep = rim_w - 2 * d.inset - 2 * d.clearance
    keep_d = rim_d - 2 * d.inset - 2 * d.clearance
    inner = _prism(p, keep, keep_d, keep, keep_d,
                   max(0.0, d.corner_r - d.inset), -1.0, STACK_GROOVE_MM + 1.0)
    return outer.cut(inner)


def _snap_groove(p: ContainerParams, d: _Derived) -> cq.Workplane:
    """
    The groove in the inner wall the lid's barbs click into.

    IT RUNS ALL THE WAY ROUND rather than only where the tabs are, so the lid
    goes on at any rotation.

    ITS UPPER FLANK IS A RAMP, NOT A CEILING. The body prints open side up, so
    a square-cut groove leaves a flat roof over itself all the way round the
    inside - measured at 545 mm2 on a 180 x 120 box, which the overhang check
    refuses outright and is right to. The flank climbs back out to the wall
    face over RAMP_RISE times its own depth, which is 30 degrees off vertical
    and prints unsupported. That is the same thing `enclosure` does to its
    board grooves and for the same measured reason.
    """
    z0 = p.height_mm - d.skirt + 1.5
    h = _barb_height(d) + SNAP_BEAD_MARGIN_MM * 2
    cut = d.bead + 0.1
    ramp = cut * RAMP_RISE
    r_out = max(0.0, d.corner_r - d.inset)

    pocket = _wall_prism(p, z0, z0 + h, d.inset - cut, r_out)
    flank = _wall_loft(p, z0 + h, z0 + h + ramp, d.inset - cut, d.inset, r_out)
    core = _wall_prism(p, z0 - 1.0, z0 + h + ramp + 1.0, d.inset, r_out)
    return pocket.union(flank).cut(core)


def _magnet_bosses(p: ContainerParams, d: _Derived) -> cq.Workplane:
    """
    A rib up the inside of the wall at each magnet, because a 6 mm magnet does
    not fit in a 2.4 mm wall.

    INWARD. Thickening the outside would change the size somebody asked for
    and show on every face. The rib runs the full height so it prints as part
    of the wall with nothing overhanging, and it stiffens the body as well.
    """
    need = p.magnet_dia_mm + 2 * MAGNET_SURROUND_MM
    depth = max(0.0, need - p.wall_mm)
    if depth <= 0.05:
        return cq.Workplane("XY")

    ribs = []
    width = p.magnet_dia_mm + 2 * MAGNET_SURROUND_MM
    for theta in d.stations:
        r_top = _wall_normal(p, theta, p.height_mm) - p.wall_mm
        r_bot = _wall_normal(p, theta, d.floor) - p.wall_mm
        # Built at the wall and running inward, then leaned with the wall so
        # the pocket stays the same depth into the material top to bottom.
        rib = (cq.Workplane("XY")
               .box(depth, width, p.height_mm - d.floor, centered=(True, True, False))
               .translate((-depth / 2.0, 0, 0)))
        lean = math.degrees(math.atan2((r_top - r_bot) / 1.0,
                                       p.height_mm - d.floor))
        rib = rib.rotate((0, 0, 0), (0, 1, 0), lean)
        rib = rib.translate((r_bot, 0, d.floor)).rotate((0, 0, 0), (0, 0, 1), theta)
        ribs.append(rib)
    return compound_of(ribs)


def _magnet_pockets(p: ContainerParams, d: _Derived, z_top: float,
                    lid: bool = False) -> cq.Workplane:
    """
    The holes the magnets sit in.

    They open UPWARD in the orientation the part prints in, both times: the
    body prints open side up and the lid prints top face down, so neither
    pocket has a ceiling over it and neither needs support. That is not a
    coincidence, it is why the lid is printed the way it is.
    """
    r = (p.magnet_dia_mm + MAGNET_POCKET_EASE_MM) / 2.0
    depth = p.magnet_thick_mm + MAGNET_POCKET_EASE_MM
    holes = []
    for theta in d.stations:
        # The same radius in both parts, because a magnet pulls on the one
        # opposite it and nothing else. It is measured in from the OUTSIDE of
        # the rim, over the middle of the pad the boss makes.
        centre = (_wall_normal(p, theta, p.height_mm)
                  - (p.magnet_dia_mm + 2 * MAGNET_SURROUND_MM) / 2.0)
        # THE TWO POCKETS OPEN TOWARDS EACH OTHER, at the joint plane. The
        # body's goes DOWN from the rim, the lid's goes UP from the underside
        # of its flange. Cutting both the same way put the lid's pocket in
        # the body's half of the joint, where there is no lid to cut, and the
        # lid came out solid - it looked right in every render.
        z0 = z_top if lid else z_top - depth
        hole = (cq.Workplane("XY", origin=(0, 0, z0 - 0.5))
                .circle(r).extrude(depth + 0.5)
                .translate((centre, 0, 0))
                .rotate((0, 0, 0), (0, 0, 1), theta))
        holes.append(hole)
    return compound_of(holes)


# ---------------------------------------------------------------------------
# the lid
# ---------------------------------------------------------------------------

def build_lid(p: ContainerParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The lid, sitting on the body: a flange over the rim and a skirt inside it.

    The skirt is the whole lid. A flat plate resting on the rim slides off;
    the skirt is what locates it, and on the clip version it is what holds it.
    """
    rim_w, rim_d = _plan(p, p.height_mm)
    z0 = p.height_mm

    flange = _prism(p, rim_w, rim_d, rim_w, rim_d, d.corner_r,
                    z0, z0 + d.lid_flange)
    skin = d.inset + d.clearance          # the skirt's outside, off the wall

    # The skirt follows the MOUTH, cut back by the clearance on every side.
    z_bot = z0 - d.skirt
    r_out = max(0.0, d.corner_r - d.inset)

    if p.closure == "hinge":
        # A HINGED LID HAS NO SKIRT, and it is not an omission. The lid turns
        # about an axis behind the back wall, so anything hanging below the
        # flange sweeps a circle straight through that wall as it opens: the
        # skirt would either have to be shorter than the clearance or the box
        # would not open. Real hinged boxes do the same thing - the lid sits
        # ON the rim and the hinge locates it.
        lid = flange
    else:
        outer = _wall_prism(p, z_bot, z0, skin, r_out)
        inner = _wall_prism(p, z_bot - 1.0, z0, skin + d.skirt_t,
                            max(0.0, r_out - d.skirt_t))
        lid = flange.union(outer.cut(inner))

    if p.closure == "clip":
        lid = lid.cut(_snap_slots(p, d, z_bot, z0))
        lid = lid.union(_snap_beads(p, d, z_bot))

    if p.closure == "magnet":
        # THE BOSS IS IN THE WAY OF THE SKIRT, and it has to be: the magnet
        # needs a thick rim and the skirt needs the mouth, and those are the
        # same place. Measured on the first build - 586 mm3 of lid inside the
        # body, which OCC will happily export as a lid that cannot be fitted.
        # The skirt is notched where each boss stands instead. It stays
        # continuous everywhere else, so it still locates the lid.
        lid = lid.cut(_boss_relief(p, d, z_bot, z0))
        lid = lid.cut(_magnet_pockets(p, d, z_top=z0, lid=True))

    if p.stackable:
        lid = lid.union(_stack_ring(p, d, z0 + d.lid_flange))

    if p.closure == "hinge":
        lid = lid.union(_knuckles(p, d, which="lid"))
        lid = lid.cut(_hinge_relief(p, d, which="lid"))
        lid = lid.cut(_knuckle_bore(p, d))

    # NO CHAMFER ON THE LID'S TOP FACE. It was there as a cosmetic break, and
    # the lid prints TOP FACE DOWN - so a 45 degree chamfer round the top edge
    # is 3.3 mm2 of 45 degree underside sitting a third of a millimetre off
    # the bed, which the overhang check refuses and the part fails for. The
    # face is on the bed anyway, which is the smoothest finish it can get.
    return lid


def _snap_slots(p: ContainerParams, d: _Derived, z_bot: float,
                z_top: float) -> cq.Workplane:
    """
    Two relief slots down each side of every snap tab.

    THIS IS THE PART THAT MAKES A SNAP-FIT WORK. Without them the bead sits on
    a closed loop of plastic, which cannot deflect at all - the lid either
    will not go on or the skirt splits. With them each tab is a cantilever
    rooted at the flange, and the deflection SNAP_BEAD_FRACTION was worked out
    for is a deflection it can actually make.
    """
    tab = max(10.0, p.magnet_dia_mm * 2)
    slots = []
    for theta in d.stations[:p.snap_tab_count]:
        for side in (-1.0, 1.0):
            r = _wall_normal(p, theta, p.height_mm)
            slot = (cq.Workplane("XY", origin=(0, 0, z_bot - 1.0))
                    .box(6.0 * (d.skirt_t + 1.0), SNAP_SLOT_MM,
                         (z_top - z_bot) - SNAP_ROOT_MM + 1.0,
                         centered=(True, True, False))
                    .translate((r, side * (tab / 2.0 + SNAP_SLOT_MM / 2.0), 0))
                    .rotate((0, 0, 0), (0, 0, 1), theta))
            slots.append(slot)
    return compound_of(slots)


def _barb_height(d: _Derived) -> float:
    """How tall the barb is: its lead-in below the apex plus its ramp above."""
    return d.bead * (1.0 + RAMP_RISE)


def _snap_beads(p: ContainerParams, d: _Derived, z_bot: float) -> cq.Workplane:
    """
    The barb on each tab: a triangular rib standing proud of the skirt.

    A HALF-ROUND BEAD IS THE OBVIOUS SHAPE AND IT DOES NOT PRINT. The lid goes
    on the bed top face down, so the barb's retaining face - the one that
    holds the box shut - is the one pointing at the bed, and on a round bead
    that face turns horizontal at the equator. The overhang check refuses it,
    correctly: it is a 0.6 mm bulge hanging off nothing.

    So it is a triangle. The lead-in below the apex is at 45 degrees and
    points AWAY from the bed, where the angle costs nothing. The retaining
    face above the apex climbs back to the skirt over RAMP_RISE times the
    barb's height, which is 30 degrees off vertical - steep enough to hold the
    lid shut, shallow enough to print with nothing under it.

    ON A ROUND SKIRT IT IS REVOLVED, NOT EXTRUDED. A straight 20 mm rib on a
    43 mm radius stands 1.2 mm proud of the arc at its ends - twice the barb
    itself - so the ends jam into the wall instead of the groove. Measured:
    9.3 mm3 of lid inside the body, on a part that looked right.
    """
    tab = max(10.0, p.magnet_dia_mm * 2)
    lead = d.bead                      # below the apex, 45 degrees
    hold = d.bead * RAMP_RISE          # above it, 30 degrees off vertical
    z = z_bot + 1.5 + SNAP_BEAD_MARGIN_MM + lead
    back = -0.3                        # buried in the skirt, so it unions
    beads = []

    for theta in d.stations[:p.snap_tab_count]:
        r = _wall_normal(p, theta, z) - d.inset - d.clearance
        profile = [(r + back, z - lead), (r + d.bead, z), (r + back, z + hold)]
        if p.shape == "round":
            # RULE 20: the revolve axis is in the workplane's LOCAL frame. On
            # XZ, local (0,0,0)->(0,1,0) IS the global Z axis; giving it in
            # global coordinates revolves about nothing useful.
            sweep = math.degrees(tab * 2.0 / max(r, 1.0))
            bead = (cq.Workplane("XZ").polyline(profile).close()
                    .revolve(sweep, (0, 0, 0), (0, 1, 0))
                    .rotate((0, 0, 0), (0, 0, 1), theta - sweep / 2.0))
        else:
            bead = (cq.Workplane("XZ").polyline(profile).close()
                    .extrude(tab, both=True)
                    .rotate((0, 0, 0), (0, 0, 1), theta))
        beads.append(bead)
    return compound_of(beads)


def _stack_ring(p: ContainerParams, d: _Derived, z_top: float) -> cq.Workplane:
    """The raised ring on the lid that the next container's groove sits over."""
    rim_w, rim_d = _plan(p, p.height_mm)
    outer = _prism(p, rim_w - 2 * d.clearance, rim_d - 2 * d.clearance,
                   rim_w - 2 * d.clearance, rim_d - 2 * d.clearance,
                   d.corner_r, z_top - 0.01, z_top + STACK_GROOVE_MM - 0.5)
    inner = _prism(p, rim_w - 2 * d.inset, rim_d - 2 * d.inset,
                   rim_w - 2 * d.inset, rim_d - 2 * d.inset,
                   max(0.0, d.corner_r - d.inset), z_top - 1.0,
                   z_top + STACK_GROOVE_MM)
    return outer.cut(inner)


# ---------------------------------------------------------------------------
# the hinge
# ---------------------------------------------------------------------------

def _knuckle_r(p: ContainerParams) -> float:
    return p.pin_dia_mm / 2.0 + 1.6


def _hinge_axis(p: ContainerParams, d: _Derived) -> tuple[float, float]:
    """
    Where the pin runs: just behind the back wall, ON THE JOINT PLANE.

    The joint plane - the rim - is the only height that works, and the first
    attempt put the axis above it. A lid hinged above its own joint has to
    lift before it can turn, so it jams; one hinged below it has to pass
    through the body. On the plane, the lid simply rotates about the back top
    edge, which is what a hinged box does.

    Behind the wall by half a knuckle: enough that the barrel is still
    embedded in the wall it is attached to, and not so far that the lid
    stands off the rim when it shuts.
    """
    back = _wall_normal(p, 90.0, p.height_mm)
    return (-(back + _knuckle_r(p) * 0.5), p.height_mm)


def _hinge_spans(p: ContainerParams, d: _Derived) -> tuple[list, list]:
    """
    Where along the pin each knuckle sits: two on the body, one between them.

    The gap either side is the material's clearance, doubled. A knuckle that
    is a sliding fit on its neighbours is a hinge that binds the moment the
    first layer is a little wide.
    """
    span = min(40.0, _plan(p, p.height_mm)[0] * 0.5)
    lid_w = span * 0.4
    gap = d.clearance * 2
    outer = (span - lid_w) / 2.0 - gap
    body = [(-span / 2.0, outer), (span / 2.0 - outer, outer)]
    lid = [(-lid_w / 2.0, lid_w)]
    return (body, lid)


def _hinge_relief(p: ContainerParams, d: _Derived, which: str) -> cq.Workplane:
    """
    The room each part has to leave for the OTHER part's knuckles.

    The knuckles straddle the joint plane, so each one reaches into the other
    part - the body's barrels stand above the rim, where the lid's flange is,
    and the lid's barrel reaches below it, into the rim. Interleaved knuckles
    only work if each part is cut away where its neighbour goes, and this is
    that cut: the neighbour's barrel, grown by the clearance, plus the pin
    bore.

    Measured before this existed: 422 mm3 of lid inside the body on a square
    box. It still exported, and it was still watertight, and the lid could
    not have been fitted.
    """
    y, z = _hinge_axis(p, d)
    body_spans, lid_spans = _hinge_spans(p, d)
    spans = lid_spans if which == "body" else body_spans
    r = _knuckle_r(p) + d.clearance
    out = []
    for x0, w in spans:
        out.append(cq.Workplane("YZ", origin=(x0 - d.clearance, y, z))
                   .circle(r).extrude(w + 2 * d.clearance))
    return compound_of(out)


def _knuckles(p: ContainerParams, d: _Derived, which: str) -> cq.Workplane:
    """
    Knuckles along the pin: two on the body, one between them on the lid.

    A print-in-place hinge is NOT what this is, and the docstring says so
    rather than letting somebody find out on the bed. A knuckle printed
    around a pin has to be built in the orientation it prints in, and neither
    a box nor its lid prints in that orientation. Three separate bodies, all
    flat on the bed, all reliable.
    """
    y, z = _hinge_axis(p, d)
    kr = _knuckle_r(p)
    body_spans, lid_spans = _hinge_spans(p, d)
    widths = lid_spans if which == "lid" else body_spans

    parts = []
    for x0, w in widths:
        if w <= 0.5:
            continue
        barrel = (cq.Workplane("YZ", origin=(x0, y, z))
                  .circle(kr).extrude(w))
        # A web into the part it belongs to, or the barrel is a cylinder
        # floating in the air beside the box. Each web stays on ITS OWN side
        # of the joint plane - the body's below the rim, the lid's above it -
        # so the two can never foul each other however the box is sized.
        # HOW FAR THE WEB HAS TO REACH: from behind the barrel forward to
        # just inside the back wall, which is one and a half knuckle radii
        # plus the wall. The first version worked it out from the body's
        # half-depth instead and came to 97 mm - the web ran forward through
        # the cavity and, once it was sloped, 165 mm below the bed.
        reach = kr * 1.5 + p.wall_mm

        if which == "lid":
            # Above the joint plane, in the flange's own layers: the bed is
            # under it in the lid's print orientation, so a box is fine.
            web = (cq.Workplane("XY", origin=(x0, y - kr, z))
                   .box(w, reach, d.lid_flange, centered=(False, False, False)))
        else:
            # A GUSSET, NOT A SLAB. Below the joint plane the web stands out
            # behind the back wall with air under it, and a box there is a
            # flat ceiling: 2 103 mm2 of it, measured, on a 120 x 90 box. The
            # underside is sloped back to the wall at RAMP_RISE instead - 30
            # degrees off vertical, which prints with nothing beneath it.
            drop = reach * RAMP_RISE
            web = (cq.Workplane("YZ", origin=(x0, 0, 0))
                   .polyline([(y - kr, z), (y - kr + reach, z),
                              (y - kr + reach, z - drop)])
                   .close().extrude(w))
        parts.append(barrel.union(web))
    if not parts:
        return cq.Workplane("XY")
    out = parts[0]
    for extra in parts[1:]:
        out = out.union(extra)
    return out


def _knuckle_bore(p: ContainerParams, d: _Derived) -> cq.Workplane:
    y, z = _hinge_axis(p, d)
    span = min(40.0, _plan(p, p.height_mm)[0] * 0.5) + 10.0
    return (cq.Workplane("YZ", origin=(-span / 2.0, y, z))
            .circle((p.pin_dia_mm + d.clearance * 2) / 2.0).extrude(span))


def _boss_relief(p: ContainerParams, d: _Derived, z_bot: float,
                 z_top: float) -> cq.Workplane:
    """
    A notch in the lid's skirt at each magnet boss.

    The boss has to be at the rim, because that is where the magnet pulls
    from; the skirt has to be at the mouth, because that is what locates the
    lid. They are the same place, so the skirt gives way - in four notches,
    not all the way round, so everywhere else it still does its job.
    """
    need = p.magnet_dia_mm + 2 * MAGNET_SURROUND_MM
    reach = max(0.0, need - p.wall_mm) + d.clearance + 0.2
    width = need + 2 * d.clearance
    out = []
    for theta in d.stations:
        r = _wall_normal(p, theta, p.height_mm) - p.wall_mm
        out.append(cq.Workplane("XY", origin=(0, 0, z_bot - 1.0))
                   .box(reach * 2.0, width, (z_top - z_bot) + 2.0,
                        centered=(True, True, False))
                   .translate((r - reach, 0, 0))
                   .rotate((0, 0, 0), (0, 0, 1), theta))
    return compound_of(out)


def build_pin(p: ContainerParams, d: _Derived) -> cq.Workplane:
    span = min(40.0, _plan(p, p.height_mm)[0] * 0.5)
    return (cq.Workplane("XY").cylinder(span, p.pin_dia_mm / 2.0)
            .translate((0, 0, p.pin_dia_mm / 2.0))
            .rotate((0, 0, 0), (1, 0, 0), 90))


# ---------------------------------------------------------------------------
# assembled, and on the bed
# ---------------------------------------------------------------------------

def build_core(p: ContainerParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    body = build_body(p, d, log)
    if p.closure == "open":
        return body
    parts = [body, build_lid(p, d, log)]
    if p.closure == "hinge":
        parts.append(build_pin(p, d))
    return compound_of(parts)


def build_print(p: ContainerParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    On the bed. RULE 21 - a separate function, not a rotation of the assembly.

    The body sits open side up, which is the only orientation where every wall
    is vertical and the cavity opens the way it prints (rule 23).

    THE LID IS TURNED OVER, top face down. That is not tidiness: the skirt
    then points up, so it is printed onto a face instead of hanging off one,
    and every magnet pocket opens upward instead of being a ceiling. Rotating
    the assembly would have printed the lid skirt-down, into the air.
    """
    body = build_body(p, d, log)
    if p.closure == "open":
        return body

    lid = build_lid(p, d, log)
    bb = lid.val().BoundingBox()
    lid = (lid.rotate((0, 0, 0), (1, 0, 0), 180)
           .translate((0, 0, bb.zmax)))
    lid = lid.translate((0, 0, -lid.val().BoundingBox().zmin))

    gap = 6.0
    body_bb = body.val().BoundingBox()
    lid_bb = lid.val().BoundingBox()
    lid = lid.translate((body_bb.xmax - lid_bb.xmin + gap, 0, 0))

    parts = [body, lid]
    if p.closure == "hinge":
        pin = build_pin(p, d)
        pin_bb = pin.val().BoundingBox()
        pin = pin.translate((lid.val().BoundingBox().xmax - pin_bb.xmin + gap,
                             0, -pin_bb.zmin))
        parts.append(pin)
    return compound_of(parts)


def build(params: ContainerParams, spec, base_dir: Path | None = None):
    from whittle.build.helpers import BuildResult
    from whittle.spec.schema import Assumption

    clearance = None
    try:
        from whittle import api
        clearance = api.config().material(spec.material).get("clearance_mm")
    except Exception:
        clearance = None

    d = derive(params, clearance if isinstance(clearance, (int, float)) else None)
    log = BuildLog()
    core = build_core(params, d, log)

    assumptions = []
    if params.lid_clearance_mm is None and params.closure != "open":
        assumptions.append(Assumption(
            name="lid_clearance_mm", value=d.clearance, units="mm",
            why=(
                "Not stated, so this material's own measured clearance. It is "
                "the single number that decides whether the lid comes off "
                "again, which is why it is harvested from test prints rather "
                "than chosen here."
            ),
        ))
    if params.closure == "clip" and params.snap_bead_mm is None:
        assumptions.append(Assumption(
            name="snap_bead_mm", value=d.bead, units="mm",
            why=(
                "ASSUMPTION. 35%% of the %.2f mm skirt. The cantilever that "
                "carries it can deflect roughly %.2f mm before PLA yields, so "
                "this sits inside it - but that is a calculation from a "
                "textbook strain figure, not a measurement of this filament."
                % (d.skirt_t, 0.015 * (d.skirt ** 2) / (1.5 * d.skirt_t))
            ),
        ))
    if params.floor_mm is None:
        assumptions.append(Assumption(
            name="floor_mm", value=d.floor, units="mm",
            why=(
                "Not stated, so 1.4 x the wall. The floor is what the "
                "contents press on and what gets set down on a table, so it "
                "is the one surface worth more than the wall."
            ),
        ))

    log.notes.append(
        "the body prints open side up: every wall is vertical and the cavity "
        "opens the way it prints, so nothing needs support"
    )
    if params.closure != "open":
        log.notes.append(
            "the lid prints TOP FACE DOWN so the skirt points up - printed the "
            "other way the skirt hangs in the air and every pocket in it is a "
            "ceiling"
        )
    if params.closure == "clip":
        log.notes.append(
            "each snap tab is cut free of the skirt by a slot down either "
            "side - a bead on an uncut skirt is a bead on a hoop, and a hoop "
            "does not flex"
        )
    if params.closure == "magnet":
        log.notes.append(
            "the magnets must go in facing opposite ways, or the lid will "
            "sit on one corner and push off the other"
        )
    if params.closure == "hinge":
        log.notes.append(
            "three bodies: box, lid and pin. This is NOT a print-in-place "
            "hinge - a knuckle printed around its own pin has to be built in "
            "the orientation it prints in, and neither a box nor its lid is"
        )

    bodies = {"open": 1, "lid": 2, "clip": 2, "magnet": 2, "hinge": 3}[params.closure]
    rim_w, rim_d = _plan(params, params.height_mm)
    total_h = params.height_mm + (0.0 if params.closure == "open" else d.lid_flange)

    return BuildResult(
        solid=core,
        print_solid=build_print(params, d, log),
        # A CLEARANCE IS NOT A FEATURE. `features` is checked against the
        # nozzle - anything in it has to be something the printer can draw -
        # and a clearance is the opposite of that: it is the air that is
        # deliberately smaller than one extrusion so two parts do not weld
        # together. Listed here it failed its own part for having a 0.2 mm
        # detail, which was the gap doing exactly its job. It is reported
        # under `derived` instead, where it is read and not measured.
        # A FEATURE THAT IS NOT THERE IS LEFT OUT, not reported as zero. Every
        # entry here is measured against the nozzle, and "snap bead 0.000 mm"
        # on a box with no snap failed its own build for having a detail too
        # fine to print - a detail that did not exist.
        features={k: v for k, v in (
            ("wall", params.wall_mm),
            ("floor", d.floor),
            ("skirt", None if params.closure in ("open", "hinge") else d.skirt),
            ("snap bead", d.bead if params.closure == "clip" else None),
        ) if v},
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={
            "closure": params.closure,
            "finish": params.finish,
            "compartments": params.columns * params.rows,
            "inner_wall_inset_mm": round(d.inset, 3),
            "lid_clearance_mm": d.clearance,
            "lid_flange_mm": d.lid_flange,
        },
        body_count_expected=bodies,
        nominal_mm=(rim_w, rim_d, total_h),
    )


register(Template(
    name="container",
    summary=(
        "A box or tub - square or round, straight or tapered, in one piece or "
        "divided into compartments - with a lid that drops on, clips shut on "
        "snap tabs, holds with magnets or swings on a pinned hinge. The "
        "outside can carry ribs, flutes, facets, a honeycomb, a knurl or "
        "horizontal waves rather than being four flat faces."
    ),
    makes=(
        "container", "box", "box with a lid", "box with lid", "lidded box",
        "storage box", "storage container", "tub", "bin", "small box",
        "lunch box", "lunchbox", "bento box", "snack box", "food container",
        "clip close box", "clip-close box", "snap box", "snap fit box",
        "magnetic box", "magnetic lid box", "hinged box", "hinged lid box",
        "jewellery box", "jewelry box", "trinket box", "keepsake box",
        "pill box", "stash box", "screw container", "parts container",
        "parts bin", "storage bin", "stacking box", "stacking bin",
        "nesting box", "desk pot", "pen pot", "pencil pot", "canister",
        "jar", "pot", "tub with lid", "sugar jar", "coffee canister",
        "battery box", "sd card box", "seed box", "tea caddy",
    ),
    params_model=ContainerParams,
    builder=build,
    anchors=("floor", "rim", "lid", "skirt"),
    print_notes=(
        "Body open side up, flat on the bed - no support anywhere. The lid "
        "goes TOP FACE DOWN, not the way it sits on the box: that puts the "
        "skirt upward so it prints onto a face, and puts every magnet pocket "
        "opening upward. A hinged one also needs the pin, which prints lying "
        "down beside them."
    ),
))
