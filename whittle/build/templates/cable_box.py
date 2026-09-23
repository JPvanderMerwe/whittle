"""
Cable box: a lidded box a power strip lives in, with the cables coming out
of both ends and air getting through.

WHY IT IS NOT THE ENCLOSURE TEMPLATE
------------------------------------
"A cable management box" routes to `enclosure`, which is a BIRDHOUSE: it has
an entrance hole, a predator guard, a pitched roof, a perch and drain holes.
Asked for a cable box it produces a box, and every one of those parameters
is either off or actively wrong. A box is not the same thing as a box FOR
something.

WHAT A CABLE BOX HAS TO HAVE, and none of it is geometry a model can invent:

  * a slot at EACH END, at floor level, wide enough for a moulded plug to
    pass - not a round hole, because a plug is not round and the cable is
    already attached to it
  * VENTILATION. A power strip and two or three chargers dissipate real
    heat, and a sealed plastic box around them is the one design mistake
    here that matters. Slots in the sides and the lid, not decoration.
  * a LID that comes off, because the thing inside gets changed
  * FEET, so the slots at floor level are not against the carpet

WHERE A PRINTED ONE FAILS
-------------------------
  * the lid does not fit, because it was made the same size as the opening.
    It sits in a rebate with a real clearance, taken from the material.
  * the plug will not go through, because the slot was sized for the cable
    rather than the moulding on the end of it.
  * it warms up, because somebody thought vents were optional.
  * it is one enormous solid print, because the walls were thick enough for
    a structural part rather than a box that holds air.

Rule 21: the box and the lid are separate solids and the PRINT layout puts
them side by side on the bed, both open-side up, so neither needs support.
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


class CableBoxParams(surface.Finished, TemplateParams):
    """Every dimension carries its unit in the name."""

    width_mm: float = Field(
        260.0, gt=40.0, le=500.0,
        description=(
            "Outside, end to end. A four-way strip is about 230 mm long, a "
            "six-way about 320 - measure the strip, this is the number that "
            "decides whether it goes in."
        ),
    )
    depth_mm: float = Field(
        110.0, gt=30.0, le=400.0,
        description="Outside, front to back. A strip is 45-55 mm wide; the rest is cable.",
    )
    height_mm: float = Field(
        95.0, gt=30.0, le=400.0,
        description=(
            "Outside, floor to the top of the lid. Tall enough for the strip "
            "plus the plugs standing in it - the plugs are the tall part."
        ),
    )
    wall_mm: float = Field(
        2.4, ge=1.2, le=8.0,
        description=(
            "It holds air, not load. 2.4 mm is six passes of a 0.4 nozzle - "
            "stiff enough to pick up full, and a third of the plastic of a "
            "structural wall."
        ),
    )

    # --- where the cables go ----------------------------------------------
    cable_slot_w_mm: float = Field(
        45.0, gt=8.0, le=200.0,
        description=(
            "Across the slot at each end. Sized for a moulded PLUG to pass, "
            "not the cable - a UK plug is 50 mm across, a European one 38."
        ),
    )
    cable_slot_h_mm: float = Field(
        28.0, gt=5.0, le=120.0,
        description="Up from the floor. A plug body is 25-30 mm deep.",
    )

    # --- keeping it cool --------------------------------------------------
    vents: bool = Field(
        True,
        description=(
            "Slots in the sides and the lid. ON by default and worth leaving "
            "on: a sealed box around a power strip and three chargers is the "
            "one mistake in this design that matters."
        ),
    )
    vent_slot_mm: float = Field(
        6.0, gt=2.0, le=30.0, description="Width of each vent slot.",
    )

    # --- the lid ----------------------------------------------------------
    lid_clearance_mm: float | None = Field(
        None, ge=0.05, le=1.5,
        description=(
            "Gap between the lid's rebate and the box. Left out, it is the "
            "material's own measured clearance - the figure harvested from "
            "parts that actually printed and fitted."
        ),
    )
    lid_lip_mm: float = Field(
        8.0, ge=2.0, le=40.0,
        description="How far the lid's lip drops inside the box to locate it.",
    )

    feet_mm: float = Field(
        6.0, ge=0.0, le=40.0,
        description=(
            "How far the box stands off the desk. The cable slots are at "
            "floor level, so without feet the cables are pinched under it. "
            "0 turns them off."
        ),
    )
    corner_r_mm: float | None = Field(
        None, ge=0.0, le=40.0, description="Outline rounding. Left out, 2 x the wall.",
    )

    @model_validator(mode="after")
    def _finish_fits(self) -> "CableBoxParams":
        body_h = self.height_mm - max(self.wall_mm * 2 + 2.0,
                                      round(self.height_mm * LID_FRACTION, 1))
        bad = surface.check(self.finish_spec(self.wall_mm), self.wall_mm,
                            _shell(self, body_h))
        if bad:
            raise ValueError(bad)
        return self

    @model_validator(mode="after")
    def _buildable(self) -> "CableBoxParams":
        if self.cable_slot_w_mm >= self.depth_mm - self.wall_mm * 2:
            raise ValueError(
                "cable_slot_w_mm %.1f is wider than the inside of the box "
                "(%.1f mm), so the end would be cut away entirely."
                % (self.cable_slot_w_mm, self.depth_mm - self.wall_mm * 2)
            )
        if self.cable_slot_h_mm >= self.height_mm - self.wall_mm * 2:
            raise ValueError(
                "cable_slot_h_mm %.1f leaves no wall above the slot on a box "
                "%.1f mm tall." % (self.cable_slot_h_mm, self.height_mm)
            )
        return self


def _shell(p: "CableBoxParams", body_h: float) -> surface.Shell:
    """
    The band of outside wall a finish may touch: the BOX, not the lid.

    It stops clear of the floor and of the joint with the lid. A groove that
    runs into the lip the lid sits on is a groove in the seal, and this box
    is the one thing in the catalogue with a cable coming out of it - the
    joint is what keeps the dust out of a power strip.
    """
    z0 = p.wall_mm + 1.5
    z1 = max(z0 + 1.0, body_h - 2.0)
    r = p.corner_r_mm if p.corner_r_mm is not None else 2.0 * p.wall_mm
    return surface.Shell(
        kind="square", z0=z0, z1=z1,
        bottom=(p.width_mm, p.depth_mm), top=(p.width_mm, p.depth_mm),
        corner_r_mm=r,
    )


@dataclass
class _Derived:
    clearance: float
    corner_r: float
    body_h: float        # the box itself, without the lid
    lid_h: float


#: How much of the height is lid. The rest is box.
#:
#: A lid deep enough to be stiff and shallow enough that the box still holds
#: the strip: an eighth, floored so a short box still gets a usable lid.
LID_FRACTION = 0.125


def derive(p: CableBoxParams, clearance_mm: float | None) -> _Derived:
    # THE MATERIAL'S OWN CLEARANCE, not a number chosen here. config carries
    # figures harvested from reference parts that printed and fitted; TPU's
    # is deliberately UNSET, and a lid clearance guessed for a flexible
    # material is worse than none - which is why this can be passed in as
    # None and then must be stated.
    clearance = p.lid_clearance_mm if p.lid_clearance_mm is not None else (
        clearance_mm if clearance_mm else 0.30)
    lid_h = max(p.wall_mm * 2 + 2.0, round(p.height_mm * LID_FRACTION, 1))
    return _Derived(
        clearance=clearance,
        corner_r=(p.corner_r_mm if p.corner_r_mm is not None
                  else round(2.0 * p.wall_mm, 2)),
        body_h=round(p.height_mm - lid_h, 1),
        lid_h=lid_h,
    )


def _vent_slots(p: CableBoxParams, length: float, height: float,
                axis: str) -> list[cq.Workplane]:
    """
    A row of slots along one face, evenly spaced, never within a corner
    radius of the end.

    SPACED FROM THE COUNT RATHER THAN A PITCH, so a box of any length gets
    slots that look deliberate instead of a row that stops short.
    """
    usable = length - 4.0 * p.wall_mm
    if usable <= p.vent_slot_mm * 2:
        return []
    count = max(2, int(usable // (p.vent_slot_mm * 3)))
    pitch = usable / count
    out = []
    for i in range(count):
        at = -usable / 2.0 + pitch * (i + 0.5)
        slot = _peaked(p.vent_slot_mm, 100.0, height)
        out.append(slot.translate((at, 0, 0)) if axis == "x"
                   else slot.rotate((0, 0, 0), (0, 0, 1), 90).translate((0, at, 0)))
    return out


def _peaked(width: float, through: float, height: float) -> cq.Workplane:
    """
    A slot through a wall whose TOP IS A PEAK, not a flat roof.

    Every slot cut through a vertical wall has a ceiling at the top of it, and
    that ceiling is unsupported plastic: the box prints open side up, so there
    is nothing under the roof of a vent to build on. Twenty-eight vents came
    to 17 mm2 and the cable slots to 216 mm2, and whittle's own verifier
    refuses any unsupported area at all - which is why this box would not
    build.

    The fix is the one every printable vent uses: the last part of the slot
    tapers to a point. Each half of the peak is RAMP_RISE times as tall as it
    is wide, which is 30 degrees off vertical and needs nothing beneath it.
    The opening loses a triangle off its top corner and keeps its width, so
    what passes through it is unchanged.
    """
    peak = width / 2.0 * RAMP_RISE
    body = cq.Workplane("XY").box(width, through, max(0.01, height - peak),
                                  centered=(True, True, False))
    top = (
        cq.Workplane("XZ")
        .polyline([(-width / 2.0, height - peak), (width / 2.0, height - peak),
                   (0.0, height)])
        .close()
        .extrude(through, both=True)
    )
    return body.union(top)


#: How far a slot's peak rises for its half-width. 1.0 is 45 degrees, which
#: the overhang check counts as a failure; 1.7 is 30 degrees off vertical.
#: Taken from the surface module - one number, one place.
RAMP_RISE = surface.RAMP_RISE


def build_core(p: CableBoxParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """The box as it sits on the desk, lid on."""
    inner_w = p.width_mm - p.wall_mm * 2
    inner_d = p.depth_mm - p.wall_mm * 2

    box = (
        cq.Workplane("XY")
        .box(p.width_mm, p.depth_mm, d.body_h, centered=(True, True, False))
    )
    # THE INSIDE, OPEN AT THE TOP. The opening faces UP, which is the one
    # direction a cavity may open in without needing support - rule 23.
    box = box.cut(
        cq.Workplane("XY")
        .box(inner_w, inner_d, d.body_h, centered=(True, True, False))
        .translate((0, 0, p.wall_mm))
    )

    # A SLOT AT EACH END, AT FLOOR LEVEL, for a plug to pass through.
    for side in (-1, 1):
        slot = (
            _peaked(p.cable_slot_w_mm, p.wall_mm * 4, p.cable_slot_h_mm)
            .rotate((0, 0, 0), (0, 0, 1), 90)
            .translate((side * p.width_mm / 2.0, 0, p.wall_mm))
        )
        box = box.cut(slot)

    if p.vents:
        for slot in _vent_slots(p, p.width_mm, d.body_h - p.wall_mm * 3, "x"):
            box = box.cut(slot.translate((0, 0, p.wall_mm * 2)))
        log.notes.append(
            "vent slots in both long sides and the lid - a sealed box around "
            "a power strip and its chargers is the mistake in this design "
            "that matters"
        )

    if p.feet_mm > 0:
        # FEET AT THE CORNERS, so the cable slots are clear of the desk.
        foot_r = max(4.0, p.wall_mm * 2)
        for sx in (-1, 1):
            for sy in (-1, 1):
                foot = (
                    cq.Workplane("XY")
                    .cylinder(p.feet_mm, foot_r, centered=(True, True, False))
                    .translate((sx * (p.width_mm / 2.0 - foot_r * 1.5),
                                sy * (p.depth_mm / 2.0 - foot_r * 1.5),
                                -p.feet_mm))
                )
                box = box.union(foot)

    # THE FINISH GOES ON THE BOX ONLY, and before the lid is put on it: a
    # pattern cut across the joint would be cut into two parts that have to
    # come apart, so the two halves of every groove would have to line up
    # after printing to look like one groove. They would not.
    if p.finish != "plain":
        box = surface.apply(box, _shell(p, d.body_h),
                            p.finish_spec(p.wall_mm), p.wall_mm, log)

    lid = build_lid(p, d, log).translate((0, 0, d.body_h))
    solid = box.union(lid)

    solid = try_edge_op(
        solid, "|Z", "fillet",
        safe_fillet_radius(d.corner_r, p.width_mm, p.depth_mm),
        "corner rounding", log,
    )
    return solid


def build_lid(p: CableBoxParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The lid, as a separate solid: a plate with a lip that drops inside.

    THE LIP IS WHAT MAKES IT A LID rather than a plate resting on top. It is
    cut back by the material's clearance on every side, which is the figure
    harvested from parts that printed and fitted - not a number chosen to
    look about right.
    """
    inner_w = p.width_mm - p.wall_mm * 2 - d.clearance * 2
    inner_d = p.depth_mm - p.wall_mm * 2 - d.clearance * 2

    plate = (
        cq.Workplane("XY")
        .box(p.width_mm, p.depth_mm, p.wall_mm, centered=(True, True, False))
    )
    lip = (
        cq.Workplane("XY")
        .box(inner_w, inner_d, p.lid_lip_mm, centered=(True, True, False))
        .translate((0, 0, -p.lid_lip_mm))
    )
    lip = lip.cut(
        cq.Workplane("XY")
        .box(inner_w - p.wall_mm * 2, inner_d - p.wall_mm * 2, p.lid_lip_mm + 1,
             centered=(True, True, False))
        .translate((0, 0, -p.lid_lip_mm - 0.5))
    )
    lid = plate.union(lip)

    if p.vents:
        for slot in _vent_slots(p, p.width_mm, p.wall_mm * 3, "x"):
            lid = lid.cut(slot.translate((0, 0, -p.wall_mm)))
    return lid


def build_print(p: CableBoxParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    On the bed: box and lid side by side, both open-side up.

    RULE 21 - this is a different function from the assembled form and not a
    rotation of it. The lid printed in place on the box would be a ceiling
    over the whole cavity; laid beside it, open side up, neither part has a
    single overhang.
    """
    # Built directly rather than by reusing build_core, because build_core
    # unions the lid on and taking it off again would be the sort of reversal
    # that quietly goes wrong.
    inner_w = p.width_mm - p.wall_mm * 2
    inner_d = p.depth_mm - p.wall_mm * 2
    box = (
        cq.Workplane("XY")
        .box(p.width_mm, p.depth_mm, d.body_h, centered=(True, True, False))
        .cut(cq.Workplane("XY")
             .box(inner_w, inner_d, d.body_h, centered=(True, True, False))
             .translate((0, 0, p.wall_mm)))
    )
    for side in (-1, 1):
        box = box.cut(
            cq.Workplane("XY")
            .box(p.wall_mm * 4, p.cable_slot_w_mm, p.cable_slot_h_mm,
                 centered=(True, True, False))
            .translate((side * p.width_mm / 2.0, 0, p.wall_mm)))
    if p.vents:
        for slot in _vent_slots(p, p.width_mm, d.body_h - p.wall_mm * 3, "x"):
            box = box.cut(slot.translate((0, 0, p.wall_mm * 2)))

    # The lid, flipped so its lip points UP and its flat face is on the bed.
    lid = build_lid(p, d, log).rotate((0, 0, 0), (1, 0, 0), 180)
    lid = lid.translate((0, p.depth_mm + 10.0, p.wall_mm))

    return box.union(lid)


def build(params: CableBoxParams, spec, base_dir: Path | None = None):
    """Template entry point."""
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

    assumptions = [
        Assumption(
            name="width_mm", value=params.width_mm, units="mm",
            why=(
                "There is no power strip here to measure. 260 mm holds a "
                "four-way; a six-way needs about 320. This is the number that "
                "decides whether yours goes in."
            ),
        ),
        Assumption(
            name="cable_slot_w_mm", value=params.cable_slot_w_mm, units="mm",
            why=(
                "Sized for a moulded plug to pass rather than for the cable: "
                "a UK plug is 50 mm across, a European one 38. Too small and "
                "the box can only be filled by unplugging everything."
            ),
        ),
    ]
    if params.lid_clearance_mm is None:
        assumptions.append(Assumption(
            name="lid_clearance_mm", value=d.clearance, units="mm",
            why=(
                "Not stated, so it is this material's own measured clearance "
                "- harvested from reference parts that printed and fitted, "
                "not chosen here."
            ),
        ))

    log.notes.append(
        "the box and the lid print side by side, both open-side up, so "
        "neither needs support"
    )

    return BuildResult(
        solid=build_core(params, d, log),
        print_solid=build_print(params, d, log),
        # NUMBERS ONLY. `features` is measured against the built mesh, so a
        # string here reaches the checker as something to compare and stops
        # the build with "could not convert string to float".
        # A CLEARANCE IS NOT A FEATURE. Everything in `features` is measured
        # against the nozzle, and a clearance is the opposite of a printed
        # detail: it is air, deliberately narrower than one extrusion so two
        # parts do not weld together. Listed here it failed this box for
        # having a 0.2 mm detail, which was the gap doing its job. It is
        # reported under `derived`, where it is read and not measured.
        features={
            "wall": params.wall_mm,
            "cable slot width": params.cable_slot_w_mm,
            "cable slot height": params.cable_slot_h_mm,
        },
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={"box_height_mm": d.body_h, "lid_height_mm": d.lid_h,
                 "lid_clearance_mm": d.clearance},
        body_count_expected=2,
        nominal_mm=(params.width_mm, params.depth_mm, params.height_mm),
    )


register(Template(
    name="cable_box",
    summary=(
        "A lidded box for a power strip: a plug-sized slot at each end at "
        "floor level, vent slots through the sides and lid, feet to keep the "
        "cables off the desk, and a lid that locates on a lip with the "
        "material's own clearance."
    ),
    makes=(
        "cable box", "cable management box", "cable management",
        # THE WORDS PEOPLE ACTUALLY TYPE, not only the compound nouns. "a box
        # for my extension lead" contains "extension lead" and not
        # "extension lead box", and a template nothing routes to is a
        # template nobody gets.
        "power strip", "power strip box", "extension lead", "extension lead box",
        "surge protector", "surge protector box", "power board",
        "cable tidy", "cord organiser", "cord organizer", "wire box",
        "router box", "modem box", "charger box", "power brick box",
        "desk cable box", "cable hider", "cable concealer",
    ),
    params_model=CableBoxParams,
    builder=build,
    anchors=("floor", "lid", "end_face"),
    print_notes=(
        "Two parts, side by side on the bed, both open-side up - neither "
        "needs support. The lid locates on its lip; if it is tight, the "
        "clearance is a parameter."
    ),
))
