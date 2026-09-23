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
