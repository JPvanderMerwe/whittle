"""
A template knows what the object IS. That is the whole difference.

THE RUN THIS FILE COMES FROM. Asked for "create a phone stand that's
unique", whittle composed primitives and produced a 100 x 100 x 30 mm SOLID
BLOCK - 220 cm3, about 280 g of filament - with one 5 mm slot across the
top. A phone with a case is 8 to 12 mm thick, so the phone did not fit the
slot; if it had, it would have stood bolt upright; and nothing stopped it
sliding out.

EVERY CHECK PASSED. Watertight, fitted the bed, needed no support, plausible
dimensions. Nothing in this engine asks whether the thing is the object that
was asked for, and a block with a slit in it passes everything.

So these tests do ask. Not "does it build" - the old block built. They ask
whether the thing has the properties that make it the object: does the phone
fit, does it lean, will it tip, can it be charged, is it a shell or a brick.
"""

from __future__ import annotations

import math

import pytest

from whittle.build.helpers import BuildLog
from whittle.build.templates.cable_box import CableBoxParams
from whittle.build.templates.cable_box import build as build_box
from whittle.build.templates.stand import StandParams, derive
from whittle.build.templates.stand import build as build_stand


class _Spec:
    material = "petg"


# ---------------------------------------------------------------------------
# the stand
# ---------------------------------------------------------------------------


def test_a_phone_actually_fits_the_slot():
    """
    The block's slot was 5 mm wide. A cased phone is 10-13. The slot is cut
    from the device thickness rather than chosen.
    """
    p = StandParams(device_thickness_mm=11.0)
    d = derive(p)
    assert d.slot_w > p.device_thickness_mm, (
        "the slot is %.1f mm and the device is %.1f" % (d.slot_w, p.device_thickness_mm)
    )
    assert d.slot_w - p.device_thickness_mm <= 3.0, (
        "%.1f mm of slop - the phone rattles" % (d.slot_w - p.device_thickness_mm)
    )


def test_it_leans_and_does_not_stand_the_phone_upright():
    """A stand that holds a phone vertical is a slot in a block."""
    p = StandParams(lean_deg=65.0)
    result = build_stand(p, _Spec())
    box = result.solid.val().BoundingBox()

    # THE BACKREST'S RISE, NOT THE WHOLE PART'S HEIGHT. The first version of
    # this compared the total height against the backrest length and forgot
    # the base is under it - the stand was leaning correctly and the test
    # said it was upright.
    rise = box.zlen - derive(p).base_height
    assert rise < p.back_height_mm * 0.98, (
        "a %.0f mm backrest rises %.0f mm - it is standing upright"
        % (p.back_height_mm, rise)
    )
    assert rise > p.back_height_mm * 0.5, "it is barely leaning back at all"

    # AND STEEPER MEANS TALLER, which is the property "it leans" actually
    # means: the angle is doing something.
    steep = build_stand(StandParams(lean_deg=80.0), _Spec()).solid.val().BoundingBox()
    shallow = build_stand(StandParams(lean_deg=45.0), _Spec()).solid.val().BoundingBox()
    assert steep.zlen > shallow.zlen


def test_it_cannot_tip_backwards():
    """
    THE FAILURE NOBODY NOTICES UNTIL THEY PUT A PHONE IN IT. The weight acts
    behind the slot, so the base has to reach back further than the backrest
    leans.
    """
    for lean in (40.0, 55.0, 65.0, 80.0):
        p = StandParams(lean_deg=lean)
        d = derive(p)
        reach = p.back_height_mm * math.cos(math.radians(lean))
        assert d.base_depth > reach, (
            "at %.0f deg the backrest reaches %.0f mm back and the base is "
            "only %.0f mm deep" % (lean, reach, d.base_depth)
        )


def test_there_is_a_lip_and_it_is_sized_against_the_device():
    p = StandParams(device_thickness_mm=11.0)
    assert derive(p).lip >= 2.0
    thick = derive(StandParams(device_thickness_mm=20.0)).lip
    thin = derive(StandParams(device_thickness_mm=8.0)).lip
    assert thick > thin, "the lip does not scale with what it is holding"


def test_it_can_be_charged_while_it_stands():
    """
    A desk stand that only works unplugged is the opposite of a desk stand.
    Measured by volume: the channel removes material.
    """
    with_slot = build_stand(StandParams(cable_slot=True), _Spec())
    without = build_stand(StandParams(cable_slot=False), _Spec())
    assert with_slot.solid.val().Volume() < without.solid.val().Volume(), (
        "the cable channel removed nothing"
    )


def test_it_is_a_shell_and_not_a_brick():
    """
    THE NUMBER THAT STARTED THIS. The composed block was 220 cm3 - about
    280 g of filament and most of a day's printing, for a phone stand.
    """
    result = build_stand(StandParams(), _Spec())
    box = result.solid.val().BoundingBox()
    volume_cm3 = result.solid.val().Volume() / 1000.0
    envelope_cm3 = (box.xlen * box.ylen * box.zlen) / 1000.0

    assert volume_cm3 < 60.0, "%.0f cm3 for a phone stand" % volume_cm3
    assert volume_cm3 / envelope_cm3 < 0.35, (
        "it fills %.0f%% of its own bounding box - that is a block"
        % (100.0 * volume_cm3 / envelope_cm3)
    )


def test_a_stand_it_cannot_make_is_refused_rather_than_built_wrong():
    """
    Bounds a builder can enforce - which is what rule 31 says a template is
    for. A wall thicker than the slot would silently close it.
    """
    with pytest.raises(ValueError) as caught:
        StandParams(device_thickness_mm=4.0, wall_mm=6.0)
    assert "too thick" in str(caught.value)


# ---------------------------------------------------------------------------
# the cable box
# ---------------------------------------------------------------------------


def test_a_plug_fits_through_the_end():
    """
    Sized for the moulded plug, not the cable: the cable is already attached
    to the plug, so a cable-sized hole means unplugging everything to fill
    the box.
    """
    p = CableBoxParams()
    assert p.cable_slot_w_mm >= 35.0, "a plug moulding is 38-50 mm across"
    assert p.cable_slot_h_mm >= 20.0


def test_it_is_vented_and_the_vents_are_real():
    """
    A sealed plastic box around a power strip and three chargers is the one
    mistake in this design that matters. Measured by volume rather than by
    trusting the flag.
    """
    vented = build_box(CableBoxParams(vents=True), _Spec())
    sealed = build_box(CableBoxParams(vents=False), _Spec())
    removed = (sealed.solid.val().Volume() - vented.solid.val().Volume()) / 1000.0
    assert removed > 5.0, "the vents removed %.1f cm3 - they are decoration" % removed


def test_the_lid_is_a_separate_part_that_fits():
    """
    Two bodies, and the lid is cut back by the material's own measured
    clearance rather than a number chosen to look right.
    """
    result = build_box(CableBoxParams(), _Spec())
    assert result.body_count_expected == 2

    clearance = result.derived["lid_clearance_mm"]
    assert 0.05 <= clearance <= 1.0, clearance
    assert any(a.name == "lid_clearance_mm" for a in result.assumptions), (
        "a clearance nobody stated was used without saying so"
    )


def test_both_parts_print_without_support():
    """
    Rule 21: the print layout is its own function, not a rotation of the
    assembled one. Box and lid side by side, both open-side up - the lid
    printed on the box would be a ceiling over the whole cavity.
    """
    result = build_box(CableBoxParams(), _Spec())
    assembled = result.solid.val().BoundingBox()
    on_bed = result.print_solid.val().BoundingBox()

    assert on_bed.ylen > assembled.ylen, (
        "the print layout is no wider than the assembled box, so the lid is "
        "still on top of it"
    )
    assert on_bed.zlen < assembled.zlen, "the layout is no flatter than assembled"


def test_a_box_that_cannot_hold_its_own_slot_is_refused():
    with pytest.raises(ValueError) as caught:
        CableBoxParams(depth_mm=40.0, cable_slot_w_mm=60.0)
    assert "wider than the inside" in str(caught.value)


# ---------------------------------------------------------------------------
# and the words reach them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("request_text, expected", [
    ("create a phone stand thats unique", "stand"),
    ("a stand for my tablet", "stand"),
    ("a cable management box", "cable_box"),
    ("a box for my extension lead", "cable_box"),
    ("a cable tidy for the desk", "cable_box"),
])
def test_the_words_people_use_reach_the_template(request_text, expected):
    """
    A template nothing routes to is a template nobody gets. `makes` is the
    only thing connecting what somebody types to the object that knows how
    to build itself.
    """
    from whittle.spec import registry

    hits = [name for name in registry.names()
            if any(word in request_text.lower()
                   for word in registry.get(name).makes)]
    assert expected in hits, "%r reached %s" % (request_text, hits or "nothing")


# ---------------------------------------------------------------------------
# gridfinity: a specification, not an opinion
# ---------------------------------------------------------------------------


def test_the_grid_is_the_published_standard():
    """
    EVERYTHING ELSE IN THIS CATALOGUE ENCODES AN OPINION. This encodes a
    SPECIFICATION, and a bin 0.5 mm out does not fit the baseplate somebody
    has already printed.
    """
    from whittle.build.templates import gridfinity as G

    assert G.PITCH_MM == 42.0
    assert G.FOOTPRINT_MM == 41.5
    assert G.HEIGHT_UNIT_MM == 7.0
    assert G.FOOT_TOTAL_MM == 4.75
    assert (G.FOOT_LOWER_CHAMFER_MM, G.FOOT_STRAIGHT_MM,
            G.FOOT_UPPER_CHAMFER_MM) == (0.8, 1.8, 2.15)


def test_a_bin_is_exactly_the_size_the_grid_says():
    """
    A 2x1 bin is 83.5 mm, not 84: the 0.5 mm clearance is counted once
    across the whole bin, not once per cell. Getting that wrong gives a bin
    that binds in a multi-cell pocket.
    """
    from whittle.build.templates.gridfinity import GridfinityParams
    from whittle.build.templates.gridfinity import build as build_grid

    result = build_grid(GridfinityParams(units_x=2, units_y=1, units_z=3), _Spec())
    box = result.solid.val().BoundingBox()
    assert round(box.xlen, 1) == 83.5
    assert round(box.ylen, 1) == 41.5
    assert round(box.zlen, 1) == 21.0


def test_the_foot_profile_is_the_one_that_seats():
    """
    THE WHOLE STANDARD IS THIS SHAPE. Measured on the built solid rather
    than trusted: sections across the foot at each step of the profile.
    """
    import cadquery as cq

    from whittle.build.templates.gridfinity import FOOTPRINT_MM, _foot

    foot = _foot(FOOTPRINT_MM, FOOTPRINT_MM)

    def across(z: float) -> float:
        slab = cq.Workplane("XY").box(200, 200, 0.02).translate((0, 0, z))
        return foot.intersect(slab).val().BoundingBox().xlen

    # Bottom face: 41.5 - 2 x (0.8 + 2.15) = 35.6. Measured 0.05 up the
    # 45-degree chamfer, so 0.1 wider.
    assert abs(across(0.05) - 35.7) < 0.2, across(0.05)
    # The straight section, which is where it grips.
    assert abs(across(0.8) - 37.2) < 0.2, across(0.8)
    assert abs(across(2.6) - 37.2) < 0.2, across(2.6)
    # And out to the full footprint at the top.
    assert abs(across(4.70) - 41.4) < 0.2, across(4.70)


def test_usable_depth_is_reported_because_it_is_not_the_height():
    """
    A 3U bin stands 21 mm and holds about 14 - the foot takes the first
    unit. Anybody sizing a bin to what goes in it needs that said, and it is
    the mistake everybody makes once.
    """
    from whittle.build.templates.gridfinity import GridfinityParams
    from whittle.build.templates.gridfinity import build as build_grid

    result = build_grid(GridfinityParams(units_z=3), _Spec())
    assert result.derived["height_mm"] == 21.0
    assert 12.0 < result.derived["usable_depth_mm"] < 16.0
    assert any(a.name == "units_z" for a in result.assumptions)


# ---------------------------------------------------------------------------
# the same words, a different take
# ---------------------------------------------------------------------------


def test_asking_twice_gives_a_different_design():
    """
    THE COMPLAINT THIS ANSWERS. A template's defaults are fixed, so an
    under-specified request has exactly one answer - correct for
    reproducibility and useless as a design tool. Somebody asking again is
    asking for something else.
    """
    from whittle.agent.variations import a_different_take

    seen = [tuple(sorted(a_different_take("stand", {}, n).items()))
            for n in range(5)]
    assert len(set(seen)) == len(seen), "two asks gave the same design: %s" % seen
    assert seen[0] == (), "the first ask should be the canonical design"


def test_a_value_somebody_stated_is_never_moved():
    """
    `params` holds what the request pinned. A request that named the lean
    gets that lean every time - varying it would be the machine overruling
    the person, which is the opposite of the point.
    """
    from whittle.agent.variations import a_different_take

    for n in range(6):
        out = a_different_take("stand", {"lean_deg": 70.0}, n)
        assert out["lean_deg"] == 70.0, out


def test_a_template_with_nothing_to_vary_is_left_alone():
    from whittle.agent.variations import a_different_take

    assert a_different_take("no_such_template", {"a": 1}, 3) == {"a": 1}


def test_gridfinity_never_varies_the_grid():
    """
    The pitch, the footprint and the foot profile ARE the standard. A
    "variant" that moved any of them would not drop into anybody's
    baseplate, which is the entire point of the thing.
    """
    from whittle.agent.variations import AXES

    varied = {field for field, _values in AXES["gridfinity"]}
    forbidden = {"units_x", "units_y", "pitch_mm", "footprint_mm"}
    assert not (varied & forbidden), varied & forbidden
