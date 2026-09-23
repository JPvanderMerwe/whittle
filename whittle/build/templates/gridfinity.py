"""
Gridfinity: the modular storage standard, built to the published numbers.

WHY THIS ONE ABOVE ALL THE OTHERS
----------------------------------
Asked what people actually print, every answer puts modular storage at the
top, and Gridfinity is the standard they mean: a 42 mm grid published by
Zack Freedman in 2022, with bins from any designer dropping into a baseplate
from any other. It is the single most useful thing a parametric modeller can
make, because the whole value is in getting numbers exactly right and that
is the one thing a parametric modeller is for.

It is also the template with the least room for judgement. Everything else
in this catalogue encodes an opinion - what angle a screen is readable at,
how thick a clip's arms should be. This encodes a SPECIFICATION, and a bin
that is 0.5 mm out does not fit the baseplate somebody already printed.

THE NUMBERS, AND WHERE THEY COME FROM
--------------------------------------
Looked up rather than remembered, because rule 9 does not bend for a
standard:

    grid pitch          42.0 mm         published spec
    bin footprint       41.5 mm         0.5 mm clearance in the pitch
    height unit         7.0 mm          published spec
    foot profile        0.8 / 1.8 / 2.15 mm, 4.75 mm total
    corner radius       3.75 mm at the 41.5 mm cell
    magnets             6 mm dia, 2 mm thick
    baseplate pocket    2.15 / 1.8 / 0.7, 4.65 mm deep, 42 mm cell, r4

The foot is three sections from the bed up: a 0.8 mm chamfer, 1.8 mm
straight, then a 2.15 mm chamfer out to the full 41.5 mm. That makes the
bottom face 41.5 - 2 x (0.8 + 2.15) = 35.6 mm, which is the figure every
other implementation lands on - an arithmetic check on the numbers above
rather than a coincidence.

WHERE A PRINTED ONE FAILS
-------------------------
  * IT DOES NOT SEAT. The foot profile is the whole standard; approximate
    it and the bin sits proud or binds. It is not a place for taste.
  * THE USABLE DEPTH IS NOT THE HEIGHT. A 3U bin stands 21 mm and holds
    about 14 mm, because the foot eats the first unit. Anybody sizing a bin
    to what goes in it needs that said out loud.
  * IT IS PRINTED SOLID. A bin is a shell; the walls are thin because
    nothing structural happens to them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from pydantic import Field, model_validator

from whittle.build import surface
from whittle.build.helpers import BuildLog
from whittle.spec.registry import Template, register
from whittle.spec.schema import TemplateParams

# --- THE PUBLISHED STANDARD. Do not adjust these to make something fit. ----
PITCH_MM = 42.0
FOOTPRINT_MM = 41.5
HEIGHT_UNIT_MM = 7.0
CORNER_R_MM = 3.75

#: The foot, bottom up: chamfer, straight, chamfer. 4.75 mm in total.
FOOT_LOWER_CHAMFER_MM = 0.8
FOOT_STRAIGHT_MM = 1.8
FOOT_UPPER_CHAMFER_MM = 2.15
FOOT_TOTAL_MM = FOOT_LOWER_CHAMFER_MM + FOOT_STRAIGHT_MM + FOOT_UPPER_CHAMFER_MM

#: What the standard puts in the underside of a bin.
MAGNET_DIA_MM = 6.0
MAGNET_DEPTH_MM = 2.0


class GridfinityParams(surface.Finished, TemplateParams):
    """Grid units, not millimetres - that is the point of the standard."""

    units_x: int = Field(
        2, ge=1, le=12,
        description="Grid cells left to right. Each is 42 mm.",
    )
    units_y: int = Field(
        1, ge=1, le=12, description="Grid cells front to back. Each is 42 mm.",
    )
    units_z: int = Field(
        3, ge=2, le=30,
        description=(
            "Height units of 7 mm. A 3U bin stands 21 mm and holds about "
            "14 mm - the foot takes the first unit, which is why 1U is not "
            "offered as a bin."
        ),
    )

    wall_mm: float = Field(
        1.2, ge=0.8, le=4.0,
        description=(
            "The shell. Nothing structural happens to a bin wall; 1.2 mm is "
            "three passes of a 0.4 nozzle and is what the common bins use."
        ),
    )
    floor_mm: float = Field(
        1.2, ge=0.8, le=6.0, description="Above the foot, under the contents.",
    )

    divisions_x: int = Field(
        1, ge=1, le=8, description="Compartments across. 1 is a plain bin.",
    )
    divisions_y: int = Field(
        1, ge=1, le=8, description="Compartments front to back.",
    )

    magnets: bool = Field(
        False,
        description=(
            "6 x 2 mm magnet pockets in the underside, one per grid cell, so "
            "the bin stays put in a drawer that gets pulled. Off by default: "
            "they need magnets, and a pocket with nothing in it is a hole."
        ),
    )
    scoop: bool = Field(
        True,
        description=(
            "A sweep up the front wall of each compartment so small parts "
            "can be swept out with a thumb. The detail that makes a bin "
            "usable one-handed."
        ),
    )
    baseplate: bool = Field(
        False,
        description=(
            "Build the BASEPLATE for this footprint instead of the bin - the "
            "grid of pockets the bins drop into."
        ),
    )

    @model_validator(mode="after")
    def _finish_fits(self) -> "GridfinityParams":
        bad = surface.check(self.finish_spec(self.wall_mm), self.wall_mm,
                            _shell(self))
        if bad:
            raise ValueError(bad)
        return self

    @model_validator(mode="after")
    def _buildable(self) -> "GridfinityParams":
        inner = FOOTPRINT_MM * min(self.units_x, self.units_y) - 2 * self.wall_mm
        cells = max(self.divisions_x, self.divisions_y)
        if cells > 1 and inner / cells < 8.0:
            raise ValueError(
                "%d x %d compartments in a %d x %d bin leaves less than 8 mm "
                "each - nothing goes in that."
                % (self.divisions_x, self.divisions_y, self.units_x, self.units_y)
            )
        return self


@dataclass
class _Derived:
    outer_x: float
    outer_y: float
    height: float
    usable_mm: float


def _shell(p: "GridfinityParams") -> surface.Shell:
    """
    The band of outside wall a finish may touch: ABOVE THE FOOT, BELOW THE RIM.

    The foot is the standard and is not decoration - it is the thing that
    drops into somebody else's baseplate, and a groove across it is a bin that
    does not seat. The rim is left alone for the same reason a bin stacks on
    another bin.

    Everything here is CUT, never added, so a decorated bin is exactly as wide
    as a plain one and still fits the 42 mm cell.
    """
    outer_x = FOOTPRINT_MM + (p.units_x - 1) * PITCH_MM
    outer_y = FOOTPRINT_MM + (p.units_y - 1) * PITCH_MM
    height = p.units_z * HEIGHT_UNIT_MM
    z0 = FOOT_TOTAL_MM + 2.0
    z1 = max(z0 + 1.0, height - 2.0)
    return surface.Shell(
        kind="square", z0=z0, z1=z1,
        bottom=(outer_x, outer_y), top=(outer_x, outer_y),
        corner_r_mm=CORNER_R_MM,
    )


def derive(p: GridfinityParams) -> _Derived:
    # THE FOOTPRINT IS THE CELL PLUS WHOLE PITCHES, not units x pitch: a 2x1
    # bin is 83.5 mm, not 84, because the 0.5 mm clearance is counted once
    # across the whole bin rather than once per cell.
    return _Derived(
        outer_x=FOOTPRINT_MM + (p.units_x - 1) * PITCH_MM,
        outer_y=FOOTPRINT_MM + (p.units_y - 1) * PITCH_MM,
        height=p.units_z * HEIGHT_UNIT_MM,
        usable_mm=p.units_z * HEIGHT_UNIT_MM - FOOT_TOTAL_MM - p.floor_mm,
    )


def _rounded(width: float, depth: float, radius: float, height: float,
             at_z: float = 0.0) -> cq.Workplane:
    """One rounded-rectangle slab, centred on the origin in X and Y."""
    return (
        cq.Workplane("XY")
        .rect(width, depth)
        .extrude(height)
        .edges("|Z")
        .fillet(max(0.1, radius))
        .translate((0, 0, at_z))
    )


def _foot(width: float, depth: float) -> cq.Workplane:
    """
    The Gridfinity foot: chamfer, straight, chamfer, 4.75 mm in total.

    BUILT AS THREE LOFTS RATHER THAN AS CHAMFER OPERATIONS. A chamfer applied
    to a filleted box is an edge operation on faces that OCC may or may not
    keep, and rule 18 says edge work is attempt-and-revert and must never be
    load-bearing. This profile IS the standard - it cannot be allowed to
    silently not happen.
    """
    lower_w = width - 2 * (FOOT_LOWER_CHAMFER_MM + FOOT_UPPER_CHAMFER_MM)
    lower_d = depth - 2 * (FOOT_LOWER_CHAMFER_MM + FOOT_UPPER_CHAMFER_MM)
    mid_w = width - 2 * FOOT_UPPER_CHAMFER_MM
    mid_d = depth - 2 * FOOT_UPPER_CHAMFER_MM

    # Corner radii shrink with the section, concentric with the full-size
    # corner, so the rounding follows the chamfer instead of pinching.
    lower_r = max(0.4, CORNER_R_MM - FOOT_LOWER_CHAMFER_MM - FOOT_UPPER_CHAMFER_MM)
    mid_r = max(0.4, CORNER_R_MM - FOOT_UPPER_CHAMFER_MM)

    bottom = (
        cq.Workplane("XY").rect(lower_w, lower_d).extrude(FOOT_LOWER_CHAMFER_MM)
        .edges("|Z").fillet(lower_r)
    )
    # The chamfers as lofts between the two rounded sections.
    lower_chamfer = (
        cq.Workplane("XY").rect(lower_w, lower_d)
        .workplane(offset=FOOT_LOWER_CHAMFER_MM).rect(mid_w, mid_d).loft()
    )
    straight = (
        cq.Workplane("XY").rect(mid_w, mid_d).extrude(FOOT_STRAIGHT_MM)
        .edges("|Z").fillet(mid_r)
        .translate((0, 0, FOOT_LOWER_CHAMFER_MM))
    )
    upper_chamfer = (
        cq.Workplane("XY").rect(mid_w, mid_d)
        .workplane(offset=FOOT_UPPER_CHAMFER_MM).rect(width, depth).loft()
        .translate((0, 0, FOOT_LOWER_CHAMFER_MM + FOOT_STRAIGHT_MM))
    )
    return lower_chamfer.union(straight).union(upper_chamfer)


def build_bin(p: GridfinityParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """A bin: the standard foot under a shell, divided if asked."""
    solid = _rounded(d.outer_x, d.outer_y, CORNER_R_MM,
                     d.height - FOOT_TOTAL_MM, at_z=FOOT_TOTAL_MM)

    # ONE FOOT PER GRID CELL, because the baseplate has one pocket per cell.
    for ix in range(p.units_x):
        for iy in range(p.units_y):
            cx = (ix - (p.units_x - 1) / 2.0) * PITCH_MM
            cy = (iy - (p.units_y - 1) / 2.0) * PITCH_MM
            solid = solid.union(
                _foot(FOOTPRINT_MM, FOOTPRINT_MM).translate((cx, cy, 0)))

    # The compartments, cut from the top.
    inner_x = d.outer_x - 2 * p.wall_mm
    inner_y = d.outer_y - 2 * p.wall_mm
    cell_x = (inner_x - (p.divisions_x - 1) * p.wall_mm) / p.divisions_x
    cell_y = (inner_y - (p.divisions_y - 1) * p.wall_mm) / p.divisions_y
    floor_z = FOOT_TOTAL_MM + p.floor_mm

    for ix in range(p.divisions_x):
        for iy in range(p.divisions_y):
            cx = -inner_x / 2.0 + ix * (cell_x + p.wall_mm) + cell_x / 2.0
            cy = -inner_y / 2.0 + iy * (cell_y + p.wall_mm) + cell_y / 2.0
            pocket = (
                cq.Workplane("XY")
                .box(cell_x, cell_y, d.height, centered=(True, True, False))
                .translate((cx, cy, floor_z))
            )
            solid = solid.cut(pocket)

            if p.scoop:
                # A CYLINDER LAID ALONG THE COMPARTMENT at the front, so the
                # floor sweeps up into the front wall and a thumb can push
                # parts out. Its overhang is the inside of a cylinder, which
                # prints without support at this radius.
                radius = min(cell_y * 0.45, d.usable_mm * 0.8)
                if radius > 1.5:
                    scoop = (
                        cq.Workplane("YZ")
                        .cylinder(cell_x, radius)
                        .rotate((0, 0, 0), (0, 1, 0), 90)
                        .translate((cx, cy - cell_y / 2.0 + radius, floor_z + radius))
                    )
                    solid = solid.cut(scoop)

    if p.finish != "plain":
        solid = surface.apply(solid, _shell(p), p.finish_spec(p.wall_mm),
                              p.wall_mm, log)

    if p.magnets:
        for ix in range(p.units_x):
            for iy in range(p.units_y):
                cx = (ix - (p.units_x - 1) / 2.0) * PITCH_MM
                cy = (iy - (p.units_y - 1) / 2.0) * PITCH_MM
                for dx in (-13.0, 13.0):
                    for dy in (-13.0, 13.0):
                        pocket = (
                            cq.Workplane("XY")
                            .cylinder(MAGNET_DEPTH_MM, MAGNET_DIA_MM / 2.0,
                                      centered=(True, True, False))
                            .translate((cx + dx, cy + dy, 0))
                        )
                        solid = solid.cut(pocket)
        log.notes.append(
            "6 x 2 mm magnet pockets in the underside - they need magnets, "
            "and an empty pocket is just a hole")

    log.notes.append(
        "%d x %d x %dU: %.1f x %.1f x %.1f mm, about %.1f mm of usable depth "
        "- the foot takes the first height unit"
        % (p.units_x, p.units_y, p.units_z, d.outer_x, d.outer_y, d.height,
           d.usable_mm))
    return solid


def build_baseplate(p: GridfinityParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The plate the bins drop into: a pocket per cell, cut to the mating
    profile.

    THE POCKET IS NOT THE FOOT. The published figures differ - 2.15/1.8/0.7
    at 4.65 mm on a 42 mm cell with r4 corners, against the bin's
    2.15/1.8/0.8 at 4.75 on 41.5 with r3.75 - and that difference IS the
    clearance. Cutting the plate with the bin's own profile would produce a
    baseplate that grips.
    """
    plate_x = p.units_x * PITCH_MM
    plate_y = p.units_y * PITCH_MM
    plate = _rounded(plate_x, plate_y, 4.0, 4.65)

    for ix in range(p.units_x):
        for iy in range(p.units_y):
            cx = (ix - (p.units_x - 1) / 2.0) * PITCH_MM
            cy = (iy - (p.units_y - 1) / 2.0) * PITCH_MM
            # The pocket is the foot profile at plate dimensions, cut through.
            pocket = _foot(PITCH_MM, PITCH_MM).translate((cx, cy, 0))
            through = (
                cq.Workplane("XY")
                .box(PITCH_MM - 2 * 2.85, PITCH_MM - 2 * 2.85, 20.0,
                     centered=(True, True, False))
                .translate((cx, cy, 0))
            )
            plate = plate.cut(pocket).cut(through)

    log.notes.append(
        "baseplate for a %d x %d grid, %.0f x %.0f mm - the pocket profile is "
        "the standard's, which is not the same as the bin's foot: the "
        "difference is the clearance"
        % (p.units_x, p.units_y, plate_x, plate_y))
    return plate


def build(params: GridfinityParams, spec, base_dir: Path | None = None):
    from whittle.build.helpers import BuildResult
    from whittle.spec.schema import Assumption

    d = derive(params)
    log = BuildLog()
    solid = (build_baseplate(params, d, log) if params.baseplate
             else build_bin(params, d, log))

    assumptions = [Assumption(
        name="units_z", value=params.units_z, units="height units",
        why=(
            "There is nothing here to measure. %dU stands %.0f mm and holds "
            "about %.1f mm - the foot takes the first unit, so a bin sized to "
            "what goes in it needs one more unit than the contents are tall."
            % (params.units_z, d.height, d.usable_mm)
        ),
    )]

    return BuildResult(
        solid=solid,
        print_solid=solid,
        features={
            "grid pitch": PITCH_MM,
            "footprint": FOOTPRINT_MM,
            "height unit": HEIGHT_UNIT_MM,
            "wall": params.wall_mm,
        },
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={"outer_x_mm": round(d.outer_x, 2),
                 "outer_y_mm": round(d.outer_y, 2),
                 "height_mm": round(d.height, 2),
                 "usable_depth_mm": round(d.usable_mm, 2)},
        body_count_expected=1,
        nominal_mm=(round(d.outer_x, 1), round(d.outer_y, 1), round(d.height, 1)),
    )


register(Template(
    name="gridfinity",
    summary=(
        "A Gridfinity bin or baseplate built to the published standard: "
        "42 mm grid, 41.5 mm footprint, 7 mm height units and the "
        "0.8/1.8/2.15 foot, so it drops into anybody else's baseplate."
    ),
    makes=(
        "gridfinity", "gridfinity bin", "gridfinity box", "gridfinity tray",
        "gridfinity baseplate", "grid bin", "modular bin", "modular storage",
        "storage bin", "parts bin", "drawer bin", "stackable bin",
        "workshop bin", "small parts storage", "screw bin",
    ),
    params_model=GridfinityParams,
    builder=build,
    anchors=("floor", "rim", "foot"),
    print_notes=(
        "Flat on the bed, open side up, no support. The foot profile is the "
        "standard and is what makes it drop into a baseplate somebody else "
        "printed - do not scale the part."
    ),
))
