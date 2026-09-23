"""
Tray: a shallow open box with dividers, for a drawer or a desk.

WHY THIS ONE
------------
It is the most printed functional object there is - drawer organisers, parts
trays, desk tidies, cutlery inserts - and composing it from primitives gives
a box with a pocket, which is a coaster with ambitions.

WHAT MAKES A TRAY A TRAY, AND WHAT A PRIMITIVE DOES NOT KNOW
-------------------------------------------------------------
  * DIVIDERS. A tray with one compartment is a box. The compartments are a
    grid, and the walls between them are thinner than the outer wall because
    they carry nothing - which is where most of the plastic is saved.
  * FINGER RELIEF. A scoop in the front wall of each compartment, or you
    cannot get a screw out of a 20 mm pocket without tipping the whole tray.
    This is the detail that separates a tray somebody keeps from one they
    print once.
  * A FLAT FLOOR THAT IS THIN. The floor carries the contents straight down
    onto the drawer bottom; it does not need to be the wall thickness.
  * DRAFT-FREE VERTICAL WALLS. It prints open-side up, so every wall is
    vertical and nothing needs support. The one thing that would need it is
    the finger scoop, which is why the scoop is a cylinder cut from ABOVE
    rather than a dome.

WHERE A PRINTED ONE FAILS
-------------------------
  * it does not fit the drawer, because the outside was guessed. Measure the
    drawer: the outside is the number that matters, and the compartments are
    what is left after the walls.
  * the compartments are all the same when the things in them are not.
  * it is one solid slab, because the floor was made as thick as the walls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from pydantic import Field, model_validator

from whittle.build import surface
from whittle.build.helpers import BuildLog, safe_fillet_radius, try_edge_op
from whittle.spec.registry import Template, register
from whittle.spec.schema import TemplateParams


class TrayParams(surface.Finished, TemplateParams):
    """Every dimension carries its unit in the name."""

    width_mm: float = Field(
        180.0, gt=20.0, le=500.0,
        description=(
            "Outside, left to right. Measure the drawer - this is the number "
            "that decides whether it goes in."
        ),
    )
    depth_mm: float = Field(
        120.0, gt=20.0, le=500.0, description="Outside, front to back.",
    )
    height_mm: float = Field(
        35.0, gt=8.0, le=200.0,
        description=(
            "Outside, floor to rim. Tall enough that things do not fall out, "
            "low enough to reach into."
        ),
    )

    columns: int = Field(
        3, ge=1, le=12,
        description="Compartments left to right. 1 makes it a plain tray.",
    )
    rows: int = Field(
        1, ge=1, le=12, description="Compartments front to back.",
    )

    wall_mm: float = Field(
        2.0, ge=1.0, le=8.0, description="The outer wall. It is what gets handled.",
    )
    divider_mm: float | None = Field(
        None, ge=0.8, le=8.0,
        description=(
            "The walls between compartments. Left out, 0.8 x the outer wall - "
            "they carry nothing and this is where the plastic is saved."
        ),
    )
    floor_mm: float | None = Field(
        None, ge=0.6, le=10.0,
        description=(
            "The floor. Left out, 0.8 x the outer wall: the contents rest on "
            "the drawer through it, so it is not a structural member."
        ),
    )

    finger_scoop: bool = Field(
        True,
        description=(
            "A scoop in the front wall of each compartment. Without it you "
            "cannot get a small part out without tipping the tray - the "
            "detail that decides whether it stays in the drawer."
        ),
    )

    corner_r_mm: float | None = Field(
        None, ge=0.0, le=40.0,
        description="Outline rounding. Left out, 2 x the outer wall.",
    )

    @model_validator(mode="after")
    def _buildable(self) -> "TrayParams":
        bad = surface.check(self.finish_spec(self.wall_mm), self.wall_mm,
                            _shell(self))
        if bad:
            raise ValueError(bad)

        inner_w = self.width_mm - 2 * self.wall_mm
        cell_w = (inner_w - (self.columns - 1) * (self.divider_mm or self.wall_mm)) \
            / self.columns
        if cell_w < 8.0:
            raise ValueError(
                "%d columns across %.0f mm leaves compartments %.1f mm wide - "
                "nothing fits in that. Fewer columns or a wider tray."
                % (self.columns, self.width_mm, cell_w)
            )
        inner_d = self.depth_mm - 2 * self.wall_mm
        cell_d = (inner_d - (self.rows - 1) * (self.divider_mm or self.wall_mm)) \
            / self.rows
        if cell_d < 8.0:
            raise ValueError(
                "%d rows across %.0f mm leaves compartments %.1f mm deep."
                % (self.rows, self.depth_mm, cell_d)
            )
        return self


def _shell(p: "TrayParams") -> surface.Shell:
    """
    The band of outside wall a finish is allowed to touch.

    IT STOPS SHORT OF THE RIM AND THE FLOOR. A groove that runs off the top
    edge breaks it into a comb, and one that runs into the floor is a groove
    in the part that sits on the drawer. The bands are small on a tray
    because a tray is shallow - which is also why the rim band is only two
    millimetres rather than the three a taller box can spare.
    """
    floor = p.floor_mm if p.floor_mm is not None else 0.8 * p.wall_mm
    z0 = floor + 1.5
    z1 = max(z0 + 1.0, p.height_mm - 2.0)
    r = p.corner_r_mm if p.corner_r_mm is not None else 2.0 * p.wall_mm
    return surface.Shell(
        kind="square", z0=z0, z1=z1,
        bottom=(p.width_mm, p.depth_mm), top=(p.width_mm, p.depth_mm),
        corner_r_mm=r,
    )


@dataclass
class _Derived:
    divider: float
    floor: float
    corner_r: float
    cell_w: float
    cell_d: float


def derive(p: TrayParams) -> _Derived:
    divider = p.divider_mm if p.divider_mm is not None else round(0.8 * p.wall_mm, 2)
    floor = p.floor_mm if p.floor_mm is not None else round(0.8 * p.wall_mm, 2)
    inner_w = p.width_mm - 2 * p.wall_mm
    inner_d = p.depth_mm - 2 * p.wall_mm
    return _Derived(
        divider=divider,
        floor=floor,
        corner_r=(p.corner_r_mm if p.corner_r_mm is not None
                  else round(2.0 * p.wall_mm, 2)),
        cell_w=(inner_w - (p.columns - 1) * divider) / p.columns,
        cell_d=(inner_d - (p.rows - 1) * divider) / p.rows,
    )


def build_core(p: TrayParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The tray, open side up - which is also how it prints, so every wall is
    vertical and nothing needs support.
    """
    solid = (
        cq.Workplane("XY")
        .box(p.width_mm, p.depth_mm, p.height_mm, centered=(True, True, False))
    )

    inner_w = p.width_mm - 2 * p.wall_mm
    inner_d = p.depth_mm - 2 * p.wall_mm
    x0 = -inner_w / 2.0
    y0 = -inner_d / 2.0

    # EACH COMPARTMENT CUT SEPARATELY, rather than hollowing the whole inside
    # and adding dividers back. The material left between the cuts IS the
    # divider, so a divider can never be left floating or half a millimetre
    # out of place.
    for col in range(p.columns):
        for row in range(p.rows):
            cx = x0 + col * (d.cell_w + d.divider) + d.cell_w / 2.0
            cy = y0 + row * (d.cell_d + d.divider) + d.cell_d / 2.0
            pocket = (
                cq.Workplane("XY")
                .box(d.cell_w, d.cell_d, p.height_mm, centered=(True, True, False))
                .translate((cx, cy, d.floor))
            )
            solid = solid.cut(pocket)

            if p.finger_scoop:
                # A CYLINDER CUT DOWN THROUGH THE FRONT WALL of this
                # compartment. Cut vertically so its own overhang is a
                # vertical face, not a dome that would need support.
                radius = min(d.cell_w * 0.30, p.height_mm * 0.55)
                if radius > 2.0:
                    scoop = (
                        cq.Workplane("XY")
                        .cylinder(p.height_mm * 2, radius, centered=(True, True, False))
                        .translate((cx, cy - d.cell_d / 2.0 - d.divider / 2.0,
                                    p.height_mm - radius * 0.9))
                    )
                    solid = solid.cut(scoop)

    if p.finger_scoop:
        log.notes.append(
            "a finger scoop is cut into the front of each compartment - "
            "without one a small part cannot be lifted out without tipping "
            "the tray"
        )

    # THE FINISH GOES ON BEFORE THE CORNER ROUNDING, because rule 18 says
    # edge work is applied last and reverted if it fails. Filleting first and
    # then cutting forty grooves into the filleted solid is how a fillet that
    # worked becomes a solid that does not.
    if p.finish != "plain":
        solid = surface.apply(solid, _shell(p), p.finish_spec(p.wall_mm),
                              p.wall_mm, log)

    solid = try_edge_op(
        solid, "|Z", "fillet",
        safe_fillet_radius(d.corner_r, p.width_mm, p.depth_mm),
        "corner rounding", log,
    )
    return solid


def build(params: TrayParams, spec, base_dir: Path | None = None):
    from whittle.build.helpers import BuildResult
    from whittle.spec.schema import Assumption

    d = derive(params)
    log = BuildLog()
    core = build_core(params, d, log)

    assumptions = [Assumption(
        name="width_mm", value=params.width_mm, units="mm",
        why=(
            "There is no drawer here to measure. 180 x 120 is an ordinary "
            "desk drawer insert. The outside is the number that decides "
            "whether it goes in; the compartments are what is left."
        ),
    )]
    if params.divider_mm is None:
        assumptions.append(Assumption(
            name="divider_mm", value=d.divider, units="mm",
            why=(
                "Not stated, so 0.8 x the outer wall. The dividers carry "
                "nothing - only the outside gets handled - and this is where "
                "most of the plastic in a tray is saved."
            ),
        ))
    if params.floor_mm is None:
        assumptions.append(Assumption(
            name="floor_mm", value=d.floor, units="mm",
            why=(
                "Not stated, so 0.8 x the outer wall. The contents rest on "
                "the drawer through the floor, so it is not a structural "
                "member and does not need the wall's thickness."
            ),
        ))

    log.notes.append(
        "prints open side up: every wall is vertical, so nothing needs support"
    )

    return BuildResult(
        solid=core,
        print_solid=core,
        features={
            "wall": params.wall_mm,
            "divider": d.divider,
            "floor": d.floor,
            "compartment width": round(d.cell_w, 2),
            "compartment depth": round(d.cell_d, 2),
        },
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={"compartments": params.columns * params.rows,
                 "cell_w_mm": round(d.cell_w, 2),
                 "cell_d_mm": round(d.cell_d, 2)},
        body_count_expected=1,
        nominal_mm=(params.width_mm, params.depth_mm, params.height_mm),
    )


register(Template(
    name="tray",
    summary=(
        "A shallow open tray divided into a grid of compartments, with a "
        "finger scoop in the front of each, thin dividers and a thin floor. "
        "The outside can carry ribs, a honeycomb, a knurl or horizontal "
        "waves. Prints open side up with no support."
    ),
    makes=(
        "tray", "drawer organiser", "drawer organizer", "drawer insert",
        "desk organiser", "desk organizer", "desk tidy", "parts tray",
        "screw tray", "component tray", "sorting tray", "cutlery tray",
        "compartment box", "divider tray", "bits box", "organiser",
        "organizer", "caddy insert", "workbench tray", "tool tray",
    ),
    params_model=TrayParams,
    builder=build,
    anchors=("floor", "rim", "divider"),
    print_notes=(
        "Open side up, flat on the bed. Every wall is vertical and nothing "
        "needs support. If it is going in a drawer, measure the drawer first."
    ),
))
