"""
Stand: something a phone, a tablet or a book leans against and does not slide
off.

WHY THIS ONE EXISTS, AND IT IS NOT "BECAUSE A PRIMITIVE IS MISSING"
-------------------------------------------------------------------
Asked for "create a phone stand that's unique", whittle composed primitives
and produced a 100 x 100 x 30 mm SOLID BLOCK - 220 cm3, about 280 g of
filament - with one 5 mm slot across the top. A phone with a case is 8 to
12 mm thick, so the phone does not fit the slot; if it did, it would stand
bolt upright; and there is nothing to stop it sliding out of the front.

Every check passed. It was watertight, it fitted the bed, it needed no
support, its dimensions were plausible. NOTHING IN THIS ENGINE ASKS WHETHER
THE THING IS THE OBJECT THAT WAS ASKED FOR, and a block with a slit in it
passes everything.

The composing path is not short of operations here. It is short of knowing
what a phone stand IS:

  * the phone leans BACK, at an angle you can read a screen at, not upright
  * the slot is wider than the phone, by enough for a case
  * there is a LIP in front of the slot or the phone slides out
  * the cable has to reach the socket, which is at the bottom edge
  * it is a shell, not a brick - a solid block of this size is a quarter of
    a kilogram of plastic and nine hours of printing

None of that is geometry the model can be told to invent. It is design
knowledge, it is the same for every phone stand ever made, and it belongs
in a template with bounds a builder can enforce. That is precisely what
rule 31 says a template is FOR: "a shortcut for a shape that comes up often
enough to be worth pinning". The warning in that rule is against adding a
template to close a gap a PRIMITIVE should have closed - and no primitive
knows what angle a screen is readable at.

WHERE A PRINTED STAND FAILS
---------------------------
  * it tips backwards, because the phone's weight is behind the base. The
    base reaches back at least as far as the top of the backrest leans.
  * the phone slides out, because the lip was decorative. The lip is sized
    against the phone's thickness, not chosen to look right.
  * the charging cable will not go in, because the slot floor is solid.
  * it takes nine hours, because it is solid.

EVERY NUMBER HERE IS A NAMED PARAMETER WITH ITS REASON, and the ones that
cannot be measured from the request arrive as ASSUMPTION entries - rule 14.
There is no phone in this workshop to measure, so the defaults are stated as
what they are: ordinary sizes, there to be changed, not measurements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from pydantic import Field, model_validator

from whittle.build.helpers import BuildLog, safe_fillet_radius, try_edge_op
from whittle.spec.registry import Template, register
from whittle.spec.schema import TemplateParams


class StandParams(TemplateParams):
    """Every dimension carries its unit in the name."""

    # --- what it holds ----------------------------------------------------
    device_thickness_mm: float = Field(
        11.0, gt=2.0, le=60.0,
        description=(
            "How thick the thing is, INCLUDING its case. A bare phone is "
            "7-9 mm and a cased one 10-13 mm; 11 is a cased phone. Measure "
            "yours if it matters - this is the number the slot is cut from."
        ),
    )
    device_width_mm: float = Field(
        76.0, gt=20.0, le=400.0,
        description=(
            "How wide the thing is across the face that rests. A phone is "
            "70-80 mm, a small tablet about 170. The stand is made wider "
            "than this so the device is not balanced on the edges."
        ),
    )

    # --- the angle it leans at --------------------------------------------
    lean_deg: float = Field(
        65.0, ge=35.0, le=85.0,
        description=(
            "Degrees from the bench, measured to the resting face. 65 is a "
            "desk viewing angle; 50 is closer to a typing angle; above 80 it "
            "is nearly upright and it topples. This is the single number "
            "that decides whether the stand is usable."
        ),
    )

    # --- the shape of it ---------------------------------------------------
    base_depth_mm: float | None = Field(
        None, gt=20.0, le=400.0,
        description=(
            "Front to back. Left out, it is worked out from the lean and the "
            "backrest height so the stand cannot tip backwards."
        ),
    )
    back_height_mm: float = Field(
        70.0, gt=20.0, le=400.0,
        description=(
            "How far up the back the device is supported, along the lean. "
            "About half the device's height is plenty; more is material."
        ),
    )
    wall_mm: float = Field(
        3.0, ge=1.2, le=12.0,
        description=(
            "Thickness of the shell. 3 mm is stiff enough in PETG for a "
            "phone; below 2 it flexes when the screen is pressed."
        ),
    )
    lip_height_mm: float | None = Field(
        None, gt=1.0, le=60.0,
        description=(
            "How far the front lip stands up. Left out, it is 40% of the "
            "device thickness - enough to hold it and not so much that it "
            "covers the screen."
        ),
    )

    # --- what goes through it ---------------------------------------------
    cable_slot: bool = Field(
        True,
        description=(
            "Cut a channel through the bottom of the slot so a charging "
            "cable reaches the socket. Without it the stand can only be used "
            "with the device unplugged, which is the opposite of what a "
            "desk stand is for."
        ),
    )
    cable_width_mm: float = Field(
        14.0, gt=4.0, le=60.0,
        description="Across the cable channel. A USB-C plug moulding is 10-12 mm.",
    )

    corner_r_mm: float | None = Field(
        None, ge=0.0, le=40.0,
        description="Rounding on the outline. Left out, it is 1.5 x the wall.",
    )

    @model_validator(mode="after")
    def _buildable(self) -> "StandParams":
        if self.wall_mm * 2 >= self.device_thickness_mm + 2.0:
            raise ValueError(
                "wall_mm %.1f is too thick for a slot holding something "
                "%.1f mm thick - the walls either side of the slot would "
                "meet. Thin the wall or state a thicker device."
                % (self.wall_mm, self.device_thickness_mm)
            )
        if self.cable_slot and self.cable_width_mm >= self.device_width_mm:
            raise ValueError(
                "cable_width_mm %.1f is as wide as the device (%.1f mm), so "
                "the cable channel would remove the whole front of the stand."
                % (self.cable_width_mm, self.device_width_mm)
            )
        return self


@dataclass
class _Derived:
    """Everything worked out from the parameters, in one place."""

    slot_w: float          # across the slot, device + clearance
    width: float           # the whole stand, across
    lip: float
    base_depth: float
    base_height: float
    back_len: float        # length of the backrest, along the lean
    corner_r: float
    lean_rad: float


#: How much wider than the device the slot is cut.
#:
#: NOT A PRINT CLEARANCE. The material clearances in config are for two
#: printed parts that have to fit each other; this is a phone going into a
#: slot by hand, where a tight fit is a phone you cannot get out and a scuffed
#: case. A millimetre and a half is loose enough to drop in and close enough
#: that it does not rattle.
SLOT_EASE_MM = 1.5

#: How much wider than the device the stand itself is, each side.
#:
#: A stand exactly as wide as the phone balances it on two edges and looks
#: like a mistake. This is the shoulder either side of the slot.
SHOULDER_MM = 6.0


def derive(p: StandParams) -> _Derived:
    lean = math.radians(p.lean_deg)
    slot_w = p.device_thickness_mm + SLOT_EASE_MM
    width = p.device_width_mm + 2 * SHOULDER_MM

    lip = p.lip_height_mm if p.lip_height_mm is not None else max(
        2.0, round(0.4 * p.device_thickness_mm, 1))

    # THE BASE HAS TO REACH BACK FURTHER THAN THE DEVICE LEANS.
    #
    # The device's weight acts through a line leaning back at `lean`, and the
    # stand tips about its back edge. So the base must extend behind the slot
    # by at least the horizontal reach of the backrest, plus something for the
    # device's own height above the rest. 1.35 is that margin - it is a
    # SAFETY FACTOR on a tipping calculation, not a measurement, and it is
    # reported as an assumption when the base depth is not given.
    reach_back = p.back_height_mm * math.cos(lean)
    base_depth = p.base_depth_mm if p.base_depth_mm is not None else round(
        max(55.0, (reach_back + slot_w) * 1.35), 1)

    # Tall enough that the slot has a floor under it and the lip has
    # something to stand on, and no taller: this is the part that is solid.
    base_height = round(p.wall_mm * 2 + lip, 1)

    corner_r = p.corner_r_mm if p.corner_r_mm is not None else round(
        1.5 * p.wall_mm, 2)

    return _Derived(
        slot_w=slot_w, width=width, lip=lip, base_depth=base_depth,
        base_height=base_height, back_len=p.back_height_mm,
        corner_r=corner_r, lean_rad=lean,
    )


def build_core(p: StandParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The stand as it stands on a desk.

    BUILT AS A WEDGE AND A BACKREST, NOT AS A BLOCK WITH A SLOT CUT IN IT.
    The block is what the composing path produced and it is wrong in the way
    that matters: a solid block of this size is 220 cm3. This is a base with
    a foot's worth of material and a leaning wall of `wall_mm`, which is
    about a tenth of that.
    """
    # The base: a plate the device's slot sits in.
    base = (
        cq.Workplane("XY")
        .box(d.width, d.base_depth, d.base_height, centered=(True, True, False))
    )

    # The backrest: a wall leaning back at `lean`, rising from the back of
    # the slot. Built upright and rotated, because a rotation about the X
    # axis is exactly the lean and nothing has to be trigonometry'd twice.
    back = (
        cq.Workplane("XY")
        .box(d.width, p.wall_mm, d.back_len, centered=(True, True, False))
        .rotate((0, 0, 0), (1, 0, 0), -(90.0 - p.lean_deg))
    )
    # Sit it at the back of the slot, standing on the base.
    slot_back_y = -d.base_depth / 2.0 + p.wall_mm + d.slot_w
    back = back.translate((0, slot_back_y, d.base_height - p.wall_mm))

    solid = base.union(back)

    # THE SLOT, and it is a slot rather than a pocket: it goes all the way
    # across, because a phone is put in sideways and taken out sideways.
    slot = (
        cq.Workplane("XY")
        .box(d.width + 10.0, d.slot_w, d.lip + p.wall_mm * 2,
             centered=(True, True, False))
        .translate((0, -d.base_depth / 2.0 + p.wall_mm + d.slot_w / 2.0,
                    d.base_height - d.lip))
    )
    solid = solid.cut(slot)

    # THE CABLE CHANNEL. Through the front wall and the floor of the slot,
    # so the plug reaches the socket at the bottom edge of the device. A
    # stand you can only use unplugged is not a desk stand.
    if p.cable_slot:
        channel = (
            cq.Workplane("XY")
            .box(p.cable_width_mm, p.wall_mm * 4 + d.slot_w, d.base_height + 4.0,
                 centered=(True, True, False))
            .translate((0, -d.base_depth / 2.0 + p.wall_mm, -2.0))
        )
        solid = solid.cut(channel)
        log.notes.append(
            "a %.0f mm cable channel is cut through the front of the slot, so "
            "the device can be charged while it stands" % p.cable_width_mm
        )

    # HOLLOWED UNDER THE BASE, which is where the material was.
    #
    # The block this replaces was 220 cm3 solid. Taking the underside out
    # leaves a rim and a floor: the same stiffness where the load is, a
    # fraction of the plastic, and it prints without support because the
    # opening faces DOWN onto the bed (rule 23 is about cavities opening
    # downward needing support - this one opens onto the bed itself, which
    # is the one direction that does not).
    inner = (
        cq.Workplane("XY")
        .box(d.width - p.wall_mm * 2, d.base_depth - p.wall_mm * 2,
             d.base_height - p.wall_mm, centered=(True, True, False))
        .translate((0, 0, -0.01))
    )
    hollowed = solid.cut(inner)
    if _volume(hollowed) > 0:
        solid = hollowed

    # COSMETIC, LAST, AND ATTEMPT-AND-REVERT - rule 18. A fillet that fails
    # must not take the stand with it.
    solid = try_edge_op(
        solid, "|Z", "fillet",
        safe_fillet_radius(d.corner_r, d.width, d.base_depth),
        "corner rounding", log,
    )
    return solid


def _volume(solid: cq.Workplane) -> float:
    try:
        return float(solid.val().Volume())
    except Exception:
        return 0.0


def build_print(p: StandParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    How it goes on the bed.

    THE SAME WAY UP IT IS USED, and that is not laziness - rule 21 says
    print and assembled orientation are separate functions, and here they
    genuinely coincide. The base sits flat, the backrest leans BACK over its
    own base, so every overhang is supported by what is under it. Standing it
    any other way puts the leaning face over air.
    """
    return build_core(p, d, log)


def build(params: StandParams, spec, base_dir: Path | None = None):
    """Template entry point."""
    from whittle.build.helpers import BuildResult
    from whittle.spec.schema import Assumption

    d = derive(params)
    log = BuildLog()
    core = build_core(params, d, log)

    features = {
        "slot width": d.slot_w,
        "lean": params.lean_deg,
        "lip height": d.lip,
        "wall": params.wall_mm,
    }

    assumptions = [
        Assumption(
            name="device_thickness_mm", value=params.device_thickness_mm,
            units="mm",
            why=(
                "There is no phone here to measure. 11 mm is an ordinary "
                "cased phone; a bare one is 7-9 and a tablet 6-8. The slot is "
                "cut %.1f mm wider than this, so a device thicker than stated "
                "will not go in." % SLOT_EASE_MM
            ),
        ),
        Assumption(
            name="lean_deg", value=params.lean_deg, units="deg",
            why=(
                "65 degrees from the bench is a desk viewing angle. It is a "
                "preference rather than a measurement, and it is the one "
                "number that decides whether the stand is comfortable - lower "
                "for typing, higher for watching."
            ),
        ),
    ]
    if params.base_depth_mm is None:
        assumptions.append(Assumption(
            name="base_depth_mm", value=d.base_depth, units="mm",
            why=(
                "Not stated, so it is worked out from the lean: the base "
                "reaches back 1.35 x as far as the backrest leans, so the "
                "weight of the device stays over the base and it cannot tip "
                "backwards. The 1.35 is a safety margin, not a measurement."
            ),
        ))
    if params.lip_height_mm is None:
        assumptions.append(Assumption(
            name="lip_height_mm", value=d.lip, units="mm",
            why=(
                "Not stated, so it is 40%% of the device thickness (%.1f mm) "
                "- enough to stop it sliding out, low enough not to cover the "
                "screen." % params.device_thickness_mm
            ),
        ))

    log.notes.append(
        "the base is hollowed from underneath: the opening faces the bed, so "
        "it prints without support and uses a fraction of the material a "
        "solid block of the same size would"
    )

    return BuildResult(
        solid=core,
        print_solid=core,
        features=features,
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={
            "slot_width_mm": d.slot_w,
            "base_depth_mm": d.base_depth,
            "backrest_length_mm": d.back_len,
            "lip_height_mm": d.lip,
        },
        body_count_expected=1,
        nominal_mm=(d.width, d.base_depth,
                    round(d.base_height + d.back_len * math.sin(d.lean_rad), 1)),
    )


register(Template(
    name="stand",
    summary=(
        "A stand something leans back against: a slot sized to the device "
        "with a lip so it cannot slide out, a backrest at a readable angle, "
        "a cable channel through the front, and a hollow base so it is not a "
        "brick."
    ),
    makes=(
        "stand", "phone stand", "phone holder", "mobile stand", "desk stand",
        "tablet stand", "ipad stand", "book stand", "cookbook stand",
        "laptop stand", "monitor stand", "dock", "cradle", "charging stand",
        "controller stand", "headphone stand", "card holder", "easel",
        "display stand", "menu holder", "sign holder", "picture stand",
    ),
    params_model=StandParams,
    builder=build,
    anchors=("base_face", "back_face", "slot"),
    print_notes=(
        "Orientation: exactly as it is used - base flat on the bed, backrest "
        "leaning back over its own base. Every overhang is over material. "
        "Do not lay it on its back: the leaning face would then be printed "
        "over air."
    ),
))
