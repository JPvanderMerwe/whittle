"""
Hook: a plate on the wall and an arm that turns up, so what you hang on it
stays on it.

WHY THIS ONE
------------
It is one of the three or four things everybody prints first, and composing
it from primitives gives a cylinder sticking out of a plate - which looks
like a hook, holds a coat for about a day, and then snaps at the root.

WHERE A PRINTED HOOK FAILS, AND WHAT THAT MEANS HERE
-----------------------------------------------------
  * IT SNAPS AT THE ROOT. The load is a bending moment at the junction of
    arm and backplate, and FDM is weakest across layers. So it prints
    STANDING ON ITS BACK, like the bracket: layers run across the load
    rather than along the crack. Printed flat on its back plate it is
    roughly a third as strong, and that single choice is most of the
    difference between a hook that holds a winter coat and one that does
    not.
  * THE ROOT IS A SHARP INTERNAL CORNER, which is a stress raiser and where
    the crack starts. It gets a fillet, sized against the arm.
  * THINGS SLIDE OFF, because the arm was a straight peg. The tip turns UP
    - that is what makes it a hook rather than a dowel.
  * THE SCREW TEARS OUT, because the hole was put near the edge. The margin
    is taken from the hole diameter, not chosen.
  * THE THING WILL NOT GO ON IT. The opening - the gap between the tip and
    the backplate - has to admit whatever hangs there: a coat loop is a few
    millimetres, a bag strap is 30 or more.

EVERY NUMBER IS A NAMED PARAMETER WITH ITS REASON. What cannot be known from
the request arrives as an ASSUMPTION (rule 14): there is no coat here to
measure.
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


class HookParams(TemplateParams):
    """Every dimension carries its unit in the name."""

    # --- the plate against the wall ---------------------------------------
    plate_width_mm: float = Field(
        28.0, gt=8.0, le=200.0, description="Across the backplate.",
    )
    plate_height_mm: float = Field(
        60.0, gt=15.0, le=400.0,
        description=(
            "Up the wall. Tall enough for two screws far enough apart that "
            "the hook cannot rotate about a single one."
        ),
    )
    plate_thick_mm: float = Field(
        5.0, ge=2.0, le=25.0,
        description=(
            "Thickness of the backplate. This is what the screw pulls "
            "against, so below 3 mm the head sinks into it."
        ),
    )

    # --- the arm ----------------------------------------------------------
    reach_mm: float = Field(
        45.0, gt=10.0, le=300.0,
        description=(
            "How far the arm stands out from the wall. The moment at the "
            "root is load x this, so a long reach needs a thicker arm."
        ),
    )
    arm_thick_mm: float = Field(
        9.0, ge=3.0, le=40.0,
        description=(
            "The arm's section. 9 mm in PETG holds a coat; a bag needs more. "
            "This is the number that decides whether it snaps."
        ),
    )
    tip_rise_mm: float | None = Field(
        None, ge=0.0, le=120.0,
        description=(
            "How far the tip turns up. Left out, it is 60% of the opening - "
            "enough to stop things lifting off, not so much that they will "
            "not go on. 0 makes it a peg rather than a hook."
        ),
    )
    opening_mm: float = Field(
        22.0, gt=3.0, le=200.0,
        description=(
            "The gap between the tip and the wall - what has to pass through "
            "to get onto the hook. A coat loop is 5-10 mm, a bag strap 30-40."
        ),
    )

    # --- fixing -----------------------------------------------------------
    screw_dia_mm: float = Field(
        4.5, gt=1.5, le=20.0, description="Clearance hole for the screw shank.",
    )
    screw_count: int = Field(
        2, ge=1, le=6,
        description=(
            "Two by default: one screw is a hinge, and a hook on a hinge "
            "swings sideways under load."
        ),
    )
    countersink: bool = Field(
        True, description="Cone the hole so a countersunk head sits flush.",
    )

    root_fillet_mm: float | None = Field(
        None, ge=0.0, le=40.0,
        description=(
            "Fillet where the arm meets the plate. Left out, it is 0.8 x the "
            "arm thickness - this is where a printed hook cracks."
        ),
    )

    @model_validator(mode="after")
    def _buildable(self) -> "HookParams":
        if self.arm_thick_mm >= self.plate_height_mm * 0.8:
            raise ValueError(
                "arm_thick_mm %.1f on a plate only %.1f mm tall leaves nothing "
                "to screw through." % (self.arm_thick_mm, self.plate_height_mm)
            )
        if self.screw_dia_mm * 3 >= self.plate_width_mm:
            raise ValueError(
                "a %.1f mm screw hole in a %.1f mm wide plate leaves too "
                "little either side - it tears out."
                % (self.screw_dia_mm, self.plate_width_mm)
            )
        return self


@dataclass
class _Derived:
    tip_rise: float
    root_r: float
    margin: float
    arm_z: float          # height up the plate where the arm leaves it


#: How far a screw hole must sit from an edge, as a multiple of its diameter.
#:
#: The same figure the bracket uses and for the same reason: below this the
#: material between the hole and the edge tears out under load.
EDGE_MARGIN_RATIO = 1.4


def derive(p: HookParams) -> _Derived:
    tip = p.tip_rise_mm if p.tip_rise_mm is not None else round(
        max(3.0, 0.6 * p.opening_mm), 1)
    root = p.root_fillet_mm if p.root_fillet_mm is not None else round(
        0.8 * p.arm_thick_mm, 2)
    margin = round(EDGE_MARGIN_RATIO * p.screw_dia_mm, 2)

    # THE ARM LEAVES THE PLATE LOW, not in the middle: everything above the
    # arm is what the screws pull against, and a screw below the arm is a
    # screw the load is trying to lever out.
    arm_z = round(max(p.arm_thick_mm, p.plate_height_mm * 0.22), 1)
    return _Derived(tip_rise=tip, root_r=root, margin=margin, arm_z=arm_z)


def build_core(p: HookParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The hook as it hangs on the wall: plate in the XZ plane, arm out along
    -Y, tip turning up.
    """
    plate = (
        cq.Workplane("XY")
        .box(p.plate_width_mm, p.plate_thick_mm, p.plate_height_mm,
             centered=(True, True, False))
    )

    # The arm, out from the plate.
    arm = (
        cq.Workplane("XY")
        .box(p.arm_thick_mm, p.reach_mm, p.arm_thick_mm,
             centered=(True, True, False))
        .translate((0, -p.reach_mm / 2.0 - p.plate_thick_mm / 2.0, d.arm_z))
    )
    solid = plate.union(arm)

    # THE TIP, TURNED UP. Without this it is a peg and whatever is on it
    # slides off the moment the door is closed.
    if d.tip_rise > 0:
        tip = (
            cq.Workplane("XY")
            .box(p.arm_thick_mm, p.arm_thick_mm, d.tip_rise + p.arm_thick_mm,
                 centered=(True, True, False))
            .translate((0,
                        -p.reach_mm - p.plate_thick_mm / 2.0 + p.arm_thick_mm / 2.0,
                        d.arm_z))
        )
        solid = solid.union(tip)

    # SCREW HOLES, spread up the plate so the hook cannot rotate about one.
    span = p.plate_height_mm - 2 * d.margin
    if p.screw_count == 1:
        heights = [p.plate_height_mm - d.margin]
    else:
        step = span / (p.screw_count - 1)
        heights = [d.margin + step * i for i in range(p.screw_count)]

    for z in heights:
        # ABOVE THE ARM ONLY. A screw below the arm is one the load levers
        # straight out of the wall.
        if z < d.arm_z + p.arm_thick_mm:
            continue
        bore = (
            cq.Workplane("XZ")
            .cylinder(p.plate_thick_mm * 4, p.screw_dia_mm / 2.0)
            .translate((0, 0, z))
        )
        solid = solid.cut(bore)
        if p.countersink:
            head = (
                cq.Workplane("XZ")
                .circle(p.screw_dia_mm)
                .workplane(offset=p.screw_dia_mm)
                .circle(p.screw_dia_mm / 2.0)
                .loft()
                .translate((0, p.plate_thick_mm / 2.0, z))
            )
            solid = solid.cut(head)

    # THE ROOT FILLET. This is where a printed hook cracks - rule 18 says
    # cosmetic edge work is attempt-and-revert, and this one is structural
    # enough to be worth trying and not worth losing the part over.
    solid = try_edge_op(
        solid, "|X", "fillet",
        safe_fillet_radius(d.root_r, p.arm_thick_mm, p.plate_thick_mm),
        "root fillet", log,
    )
    return solid


def build_print(p: HookParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    On the bed: lying on its BACK PLATE, arm pointing up.

    RULE 21 - a different function, not a rotation for its own sake. The load
    on a hook is a bending moment at the root; printed with the plate flat on
    the bed the layer lines run straight across that root and it snaps along
    one. Stood on the back plate, the layers run across the load instead.

    This is the single biggest thing separating a hook that holds a coat from
    one that does not, and it is why the print orientation is not the hanging
    orientation.
    """
    return build_core(p, d, log).rotate((0, 0, 0), (1, 0, 0), 90)


def build(params: HookParams, spec, base_dir: Path | None = None):
    from whittle.build.helpers import BuildResult
    from whittle.spec.schema import Assumption

    d = derive(params)
    log = BuildLog()
    core = build_core(params, d, log)

    assumptions = [Assumption(
        name="opening_mm", value=params.opening_mm, units="mm",
        why=(
            "There is nothing here to measure. 22 mm admits a coat loop or a "
            "towel; a bag strap needs 30-40. This is what has to pass between "
            "the tip and the wall to get onto the hook."
        ),
    )]
    if params.tip_rise_mm is None:
        assumptions.append(Assumption(
            name="tip_rise_mm", value=d.tip_rise, units="mm",
            why=(
                "Not stated, so it is 60%% of the opening (%.0f mm) - enough "
                "that things do not lift off, low enough that they go on."
                % params.opening_mm
            ),
        ))
    if params.root_fillet_mm is None:
        assumptions.append(Assumption(
            name="root_fillet_mm", value=d.root_r, units="mm",
            why=(
                "Not stated, so it is 0.8 x the arm thickness. The root is "
                "where a printed hook cracks, and a sharp internal corner "
                "there is a stress raiser."
            ),
        ))

    log.notes.append(
        "prints standing on its back plate so the layers run ACROSS the "
        "bending load at the root - printed flat it is roughly a third as "
        "strong, and the root is where a hook breaks"
    )

    return BuildResult(
        solid=core,
        print_solid=build_print(params, d, log),
        features={
            "arm thickness": params.arm_thick_mm,
            "reach": params.reach_mm,
            "root fillet": d.root_r,
            "screw hole": params.screw_dia_mm,
        },
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={"tip_rise_mm": d.tip_rise, "root_fillet_mm": d.root_r,
                 "edge_margin_mm": d.margin},
        body_count_expected=1,
        nominal_mm=(params.plate_width_mm,
                    params.reach_mm + params.plate_thick_mm,
                    params.plate_height_mm),
    )


register(Template(
    name="hook",
    summary=(
        "A backplate and an arm that turns up at the tip, filleted at the "
        "root and screwed through countersunk holes above the arm. Prints "
        "standing on its back so the layers run across the load."
    ),
    makes=(
        "hook", "wall hook", "coat hook", "key hook", "hat hook", "towel hook",
        "utility hook", "j hook", "peg", "coat peg", "hanger",
        "bag hook", "cup hook", "tool hook", "headphone hook",
        "over door hook", "garage hook", "broom holder", "mug hook",
    ),
    params_model=HookParams,
    builder=build,
    anchors=("plate_face", "arm", "tip"),
    print_notes=(
        "Orientation: standing on the back plate, arm pointing up. DO NOT lay "
        "it on its back - the root would then be printed along the load and "
        "it snaps there."
    ),
))
