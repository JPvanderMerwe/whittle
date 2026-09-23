"""
Clip: a C of material that springs open, grips a round thing, and screws or
sticks to something.

WHY THIS ONE
------------
Cable clips, tool clips, broom grips, pen clips, rod holders - all the same
object with one number changed, and all of them impossible to compose from
primitives because the thing that makes a clip work is not a shape, it is
SPRING.

WHAT A PRIMITIVE DOES NOT KNOW
------------------------------
  * A CLIP IS A SPRING, AND ITS STIFFNESS IS THE WALL THICKNESS. Too thick
    and it will not go on; too thin and it will not hold, and in PETG it
    creeps and stops holding after a week. The wall is the parameter that
    matters and it is sized against the bore, not chosen.
  * THE MOUTH IS NARROWER THAN THE THING IT HOLDS. That is the whole point -
    it snaps over and stays. A mouth as wide as the bore is a hook.
  * THE MOUTH FLARES. A blunt mouth has to be pushed straight on; a flared
    one guides the cable in. This is the difference between a clip you use
    and one you fight.
  * THE OPENING FACES SIDEWAYS ON THE BED. Printed with the mouth up, every
    layer line runs across the arms and the clip snaps at the root on the
    third use - this is the same layer-direction argument as the bracket and
    the hook, and it is why print orientation is its own function.

WHERE A PRINTED CLIP FAILS
--------------------------
  * it snaps at the root of an arm, along a layer
  * it holds for a week and then does not, because PETG creeps under a
    constant strain and the arms were too thin
  * it will not go on at all, because the mouth was made the same as the
    bore and there is no lead-in
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


class ClipParams(TemplateParams):
    """Every dimension carries its unit in the name."""

    bore_mm: float = Field(
        8.0, gt=2.0, le=200.0,
        description=(
            "Across the thing being gripped. A mains cable is 6-8 mm, a broom "
            "handle 22-25, a 15 mm pipe is 15. This is the number everything "
            "else is worked out from."
        ),
    )
    length_mm: float = Field(
        14.0, gt=3.0, le=200.0,
        description="Along the thing. Longer grips better and needs more push.",
    )
    wall_mm: float = Field(
        1.8, ge=0.8, le=12.0,
        description=(
            "The arms, which ARE the spring. Thick enough to hold, thin "
            "enough to open - about 45% of the bore radius. This is the one "
            "number that decides whether the clip works, and a wall wrong for "
            "the bore is refused with the figure it should be."
        ),
    )
    mouth_fraction: float = Field(
        0.72, ge=0.30, le=0.98,
        description=(
            "How wide the mouth is as a fraction of the bore. Below 1 it "
            "snaps over and holds; at 1 it is a cradle and the thing falls "
            "out. 0.72 grips a cable firmly."
        ),
    )

    # --- how it attaches --------------------------------------------------
    back_mm: float = Field(
        4.0, ge=1.0, le=40.0,
        description="Material behind the bore, which is what it is fixed through.",
    )
    screw_dia_mm: float | None = Field(
        None, gt=1.5, le=20.0,
        description=(
            "A screw hole through the back. Left out, there is none and the "
            "clip is glued or taped - which is what most cable clips are."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _wall_follows_the_bore(cls, data):
        """
        An arm thickness nobody gave follows the bore; one somebody gave is
        theirs.

        WHY NOT JUST `float | None`. That is the nicer schema and it made
        "make it thicker" do nothing: the language parser fills an unset
        field from the schema's DEFAULT, and a derived field has none - so
        the app offered the phrase and the parser silently refused it.

        WHY NOT JUST A FIXED DEFAULT. 1.8 mm arms on a 25 mm broom handle
        will not hold, so asking for a broom clip would have to be refused
        until somebody also worked out the wall - which is the template
        being hostile about the one number it knows best.

        So: a real default in the schema, so it can be nudged, and it is
        replaced here when the caller did not name it. `mode="before"` sees
        the raw input, which is the only place "not given" and "given as
        1.8" can be told apart.
        """
        if isinstance(data, dict) and "wall_mm" not in data:
            bore = data.get("bore_mm")
            if isinstance(bore, (int, float)):
                data = dict(data)
                data["wall_mm"] = round(
                    max(MIN_WALL_MM, WALL_FRACTION * float(bore) / 2.0), 2)
        return data

    @model_validator(mode="after")
    def _buildable(self) -> "ClipParams":
        # A WALL SOMEBODY NAMED IS CHECKED AGAINST THE BORE rather than
        # silently fixed - with the figure it should be, which is more use
        # than a number changed behind their back. Bounds a builder can
        # enforce; rule 31.
        wanted = max(MIN_WALL_MM, WALL_FRACTION * self.bore_mm / 2.0)
        if self.wall_mm < wanted * 0.55:
            raise ValueError(
                "arms %.2f mm thick on a %.1f mm bore will not hold - they "
                "creep in PETG under constant strain and stop gripping. For "
                "this bore use about %.1f mm."
                % (self.wall_mm, self.bore_mm, wanted)
            )
        if self.wall_mm > wanted * 2.2:
            raise ValueError(
                "arms %.2f mm thick on a %.1f mm bore will not open far "
                "enough to go on. For this bore use about %.1f mm."
                % (self.wall_mm, self.bore_mm, wanted)
            )
        if self.screw_dia_mm and self.screw_dia_mm >= self.back_mm * 2:
            raise ValueError(
                "a %.1f mm screw hole through %.1f mm of back leaves no "
                "material around it." % (self.screw_dia_mm, self.back_mm)
            )
        return self


@dataclass
class _Derived:
    wall: float
    mouth: float
    outer_r: float


#: The arm thickness as a fraction of the bore radius, when nobody says.
#:
#: NOT A MEASURED SPRING RATE. It is the ratio the clips in this workshop's
#: reference parts use, and it holds across the range that matters: a 6 mm
#: cable clip gets 1.4 mm arms, a 25 mm broom grip gets 5. Thinner creeps in
#: PETG under constant strain and stops holding; thicker will not open.
#: Stated as an assumption every time it is used.
WALL_FRACTION = 0.45

#: Smallest arm that prints as a spring rather than as a thread.
MIN_WALL_MM = 1.2


def derive(p: ClipParams) -> _Derived:
    wall = p.wall_mm
    return _Derived(
        wall=wall,
        mouth=round(p.bore_mm * p.mouth_fraction, 2),
        outer_r=p.bore_mm / 2.0 + wall,
    )


def build_core(p: ClipParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    The clip standing as it grips: bore along Z, mouth facing +Y.
    """
    # The C: an outer cylinder with the bore taken out of it.
    body = (
        cq.Workplane("XY")
        .cylinder(p.length_mm, d.outer_r, centered=(True, True, False))
    )
    body = body.cut(
        cq.Workplane("XY")
        .cylinder(p.length_mm * 3, p.bore_mm / 2.0, centered=(True, True, False))
        .translate((0, 0, -p.length_mm))
    )

    # THE MOUTH, narrower than the bore so it snaps over and holds.
    mouth = (
        cq.Workplane("XY")
        .box(d.mouth, d.outer_r * 3, p.length_mm * 3,
             centered=(True, True, False))
        .translate((0, d.outer_r, -p.length_mm))
    )
    body = body.cut(mouth)

    # THE FLARE. Two chamfered lead-ins at the mouth so the cable is guided
    # in rather than pushed in blind. Cut as wedges rather than filleted,
    # because a fillet here is an edge operation on a face that may not exist
    # after the mouth cut - and rule 18 says edge work is attempt-and-revert
    # and must never be load-bearing.
    flare = d.wall * 0.9
    for side in (-1, 1):
        wedge = (
            cq.Workplane("XY")
            .box(flare * 2, flare * 2, p.length_mm * 3, centered=(True, True, False))
            .rotate((0, 0, 0), (0, 0, 1), 45)
            .translate((side * d.mouth / 2.0, d.outer_r, -p.length_mm))
        )
        body = body.cut(wedge)

    # THE BACK: material behind the bore to fix through.
    back = (
        cq.Workplane("XY")
        .box(d.outer_r * 2, p.back_mm, p.length_mm, centered=(True, True, False))
        .translate((0, -d.outer_r - p.back_mm / 2.0 + 0.01, 0))
    )
    solid = body.union(back)

    if p.screw_dia_mm:
        bore = (
            cq.Workplane("XZ")
            .cylinder(p.back_mm * 6, p.screw_dia_mm / 2.0)
            .translate((0, -d.outer_r - p.back_mm / 2.0, p.length_mm / 2.0))
        )
        solid = solid.cut(bore)
        log.notes.append("screwed through the back rather than glued")

    solid = try_edge_op(
        solid, "|Z", "fillet",
        safe_fillet_radius(min(1.2, d.wall * 0.4), d.wall, p.back_mm),
        "edge softening", log,
    )
    return solid


def build_print(p: ClipParams, d: _Derived, log: BuildLog) -> cq.Workplane:
    """
    On the bed: laid on its back, mouth facing sideways.

    RULE 21, and here it is the difference between a clip and a broken clip.
    The arms are a spring loaded across their own thickness; printed with the
    mouth pointing up, every layer line runs across the arms and the first
    firm push splits one off along a layer. Laid down, the layers run around
    the C and the spring works with the grain.
    """
    return build_core(p, d, log).rotate((0, 0, 0), (1, 0, 0), 90)


def build(params: ClipParams, spec, base_dir: Path | None = None):
    from whittle.build.helpers import BuildResult
    from whittle.spec.schema import Assumption

    d = derive(params)
    log = BuildLog()

    assumptions = [Assumption(
        name="bore_mm", value=params.bore_mm, units="mm",
        why=(
            "There is nothing here to measure. 8 mm is a mains cable; a 15 mm "
            "pipe is 15, a broom handle 22-25. Everything else in this clip "
            "is worked out from it."
        ),
    )]
    assumptions.append(Assumption(
        name="wall_mm", value=d.wall, units="mm",
        why=(
            "The arms ARE the spring, and about %.0f%% of the bore radius is "
            "what holds without creeping. Thinner creeps in PETG under "
            "constant strain and stops gripping after a week; thicker will "
            "not open far enough to go on. This is the number to change if it "
            "grips wrongly." % (WALL_FRACTION * 100)
        ),
    ))

    log.notes.append(
        "the mouth is %.1f mm across a %.1f mm bore, so it snaps over and "
        "holds; prints lying down so the layers run around the C rather than "
        "across the arms" % (d.mouth, params.bore_mm)
    )

    return BuildResult(
        solid=build_core(params, d, log),
        print_solid=build_print(params, d, log),
        features={
            "bore": params.bore_mm,
            "arm thickness": d.wall,
            "mouth": d.mouth,
        },
        log=log,
        assumptions=assumptions,
        scale_departures=[],
        derived={"mouth_mm": d.mouth, "wall_mm": d.wall,
                 "outer_dia_mm": round(d.outer_r * 2, 2)},
        body_count_expected=1,
        nominal_mm=(round(d.outer_r * 2, 1),
                    round(d.outer_r * 2 + params.back_mm, 1),
                    params.length_mm),
    )


register(Template(
    name="clip",
    summary=(
        "A C that springs over something round and holds it: the mouth is "
        "narrower than the bore, flared so it guides in, and the arm "
        "thickness is worked out from the bore because the arms are the "
        "spring. Prints lying down so the layers run around the C."
    ),
    makes=(
        "clip", "cable clip", "cord clip", "wire clip", "pen clip",
        "tool clip", "broom clip", "broom holder", "mop holder",
        "pipe clip", "rod clip", "hose clip", "spring clip", "snap clip",
        "cable holder", "cable tidy clip", "handle clip", "bracket clip",
    ),
    params_model=ClipParams,
    builder=build,
    anchors=("bore", "mouth", "back"),
    print_notes=(
        "Lying down, mouth facing sideways. DO NOT print it mouth-up: the "
        "arms are a spring and the layers would run straight across them."
    ),
))
