"""
A container that is a container: does the lid come off, does the snap snap,
do the magnets face each other, does the hinge open.

WHY THESE TESTS AND NOT "IT BUILT"
-----------------------------------
Every defect found while writing this template passed isValid(), exported a
watertight STL and looked correct in a render:

  * 586 mm3 of lid inside the body, because the magnet boss stood where the
    skirt goes
  * 422 mm3 of lid inside the body, because the hinge knuckles were not
    interleaved
  * a lid magnet pocket cut into thin air below the lid, so the lid came out
    solid
  * a snap bead built as a straight cylinder on a round skirt, standing 1.2 mm
    proud of the arc at its ends

Not one of those would have been caught by a build that succeeded. So the
tests below ask the questions a person would ask holding the two parts: does
this go on, does it stay on, does it come off, does it open.
"""

from __future__ import annotations

import cadquery as cq
import pytest

from whittle.build.helpers import BuildLog, probe
from whittle.build.templates import container as C
from whittle.build.templates.container import (
    ContainerParams,
    build_body,
    build_core,
    build_lid,
    build_print,
    derive,
)

CLEARANCE = 0.30
CLOSURES = ("lid", "clip", "magnet", "hinge")


def made(**kw):
    p = ContainerParams(**kw)
    d = derive(p, CLEARANCE)
    return p, d, BuildLog()


def clash(a: cq.Workplane, b: cq.Workplane) -> float:
    try:
        return a.intersect(b).val().Volume()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# the lid goes on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", ["square", "round"])
@pytest.mark.parametrize("closure", CLOSURES)
def test_the_lid_and_the_body_do_not_occupy_the_same_space(shape, closure):
    """
    THE TEST THAT FOUND EVERY BUG IN THIS FILE.

    Two solids that overlap cannot both be printed and then assembled, and
    nothing else in the pipeline notices - each one on its own is valid,
    watertight and correct.
    """
    p, d, log = made(shape=shape, closure=closure)
    assert clash(build_body(p, d, log), build_lid(p, d, log)) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("closure", CLOSURES)
def test_the_lid_is_still_clear_on_a_tapered_body(closure):
    """A taper moves every mating surface, which is where a fit goes wrong."""
    p, d, log = made(shape="square", closure=closure, taper_deg=8.0)
    assert clash(build_body(p, d, log), build_lid(p, d, log)) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("shape", ["square", "round"])
def test_the_skirt_reaches_well_down_inside_the_mouth(shape):
    """
    A lid that only touches the rim rocks and lifts off. The skirt is what
    locates it, so it has to actually go in.
    """
    p, d, log = made(shape=shape, closure="lid")
    lid = build_lid(p, d, log)
    inside = p.height_mm - lid.val().BoundingBox().zmin
    assert inside >= C.MIN_SKIRT_MM
    assert inside == pytest.approx(d.skirt, abs=0.01)


# ---------------------------------------------------------------------------
# the snap snaps
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", ["square", "round"])
def test_the_snap_bead_clears_when_shut_and_interferes_on_the_way_in(shape):
    """
    A snap-fit that never touches the wall is a loose lid; one that touches it
    when shut is a lid that was forced on and will not come off. It has to do
    BOTH: interfere partway in, clear at the bottom.
    """
    p, d, log = made(shape=shape, closure="clip")
    body = build_body(p, d, log)
    lid = build_lid(p, d, log)

    assert clash(body, lid) == pytest.approx(0.0, abs=1e-6), "shut, it must be free"
    assert clash(body, lid.translate((0, 0, 3.0))) > 1.0, "going in, it must catch"


def test_the_snap_bead_stands_proud_of_the_clearance_it_has_to_cross():
    """
    A bead smaller than the gap around the skirt does nothing at all. The
    interference is bead minus clearance, and it has to be a real number.
    """
    p, d, _ = made(closure="clip")
    assert d.bead > d.clearance
    assert d.bead - d.clearance > 0.15


def test_every_snap_tab_is_cut_free_of_the_skirt_on_both_sides():
    """
    THE THING EVERYBODY GETS WRONG. A bead on an uncut skirt sits on a closed
    hoop, which cannot deflect: the lid will not go on, or it splits. The
    relief slots are what make each tab a cantilever.

    Measured as slots, not trusted: the skirt loses material at the tab
    stations, and it loses it over most of the skirt's height.
    """
    p, d, log = made(closure="clip")
    plain, dp, lp = made(closure="lid")
    assert build_lid(p, d, log).val().Volume() < build_lid(plain, dp, lp).val().Volume()

    slots = C._snap_slots(p, d, p.height_mm - d.skirt, p.height_mm)
    assert len(slots.val().Solids()) == 2 * p.snap_tab_count
    tall = slots.val().BoundingBox().zlen
    assert tall > d.skirt - C.SNAP_ROOT_MM


def test_a_snap_bead_too_deep_for_the_wall_is_refused_with_what_is_left():
    with pytest.raises(ValueError) as caught:
        ContainerParams(closure="clip", wall_mm=1.2, snap_bead_mm=1.0)
    assert "leaving" in str(caught.value)


# ---------------------------------------------------------------------------
# the magnets face each other
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", ["square", "round"])
def test_a_real_magnet_fits_in_both_pockets_and_they_line_up(shape):
    """
    Both halves, at the same radius, opening towards each other across the
    joint. The lid's pocket was once cut BELOW the joint plane, where there is
    no lid: it removed nothing, the lid came out solid, and everything passed.
    """
    p, d, log = made(shape=shape, closure="magnet")
    body = build_body(p, d, log)
    lid = build_lid(p, d, log)
    r = p.magnet_dia_mm / 2.0

    for theta in d.stations:
        centre = (C._wall_normal(p, theta, p.height_mm)
                  - (p.magnet_dia_mm + 2 * C.MAGNET_SURROUND_MM) / 2.0)

        def disc(z0):
            return (cq.Workplane("XY", origin=(0, 0, z0)).circle(r)
                    .extrude(p.magnet_thick_mm).translate((centre, 0, 0))
                    .rotate((0, 0, 0), (0, 0, 1), theta))

        assert clash(body, disc(p.height_mm - p.magnet_thick_mm)) == pytest.approx(0.0, abs=1e-6)
        assert clash(lid, disc(p.height_mm)) == pytest.approx(0.0, abs=1e-6)


def test_the_magnet_is_covered_rather_than_open_at_the_face():
    """
    A pocket cut right through is a magnet that falls out and a lid that rings
    on the one below it. The flange grows to carry the magnet plus its cover.
    """
    p, d, _ = made(closure="magnet")
    assert d.lid_flange >= p.magnet_thick_mm + C.MAGNET_COVER_MM


def test_a_magnet_bigger_than_the_container_is_refused():
    with pytest.raises(ValueError):
        ContainerParams(closure="magnet", width_mm=30.0, depth_mm=30.0,
                        magnet_dia_mm=20.0)


# ---------------------------------------------------------------------------
# the hinge opens
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", ["square", "round"])
def test_the_hinged_lid_swings_right_open_without_hitting_the_body(shape):
    """
    A hinge that binds at 30 degrees is a hinge that snaps. Swept through the
    whole opening rather than checked shut, because shut is the one angle at
    which a wrongly placed axis looks fine.
    """
    p, d, log = made(shape=shape, closure="hinge")
    body = build_body(p, d, log)
    lid = build_lid(p, d, log)
    y, z = C._hinge_axis(p, d)
    for angle in (15, 30, 45, 60, 75, 90, 105, 120):
        turned = lid.rotate((0, y, z), (1, y, z), angle)
        assert clash(body, turned) == pytest.approx(0.0, abs=1e-6), angle


def test_the_hinge_axis_is_on_the_joint_plane():
    """
    Above it, the lid has to lift before it can turn and jams. Below it, the
    lid has to pass through the body.
    """
    p, d, _ = made(closure="hinge")
    _, z = C._hinge_axis(p, d)
    assert z == pytest.approx(p.height_mm)


def test_a_hinged_container_is_three_bodies_and_the_pin_is_one_of_them():
    p, d, log = made(closure="hinge")
    assert len(build_core(p, d, log).val().Solids()) == 3


def test_the_hinge_knuckles_are_interleaved_and_not_touching():
    """The gap either side is the material's clearance, doubled."""
    p, d, _ = made(closure="hinge")
    body_spans, lid_spans = C._hinge_spans(p, d)
    lid_x0, lid_w = lid_spans[0]
    for x0, w in body_spans:
        gap = min(abs(lid_x0 - (x0 + w)), abs(x0 - (lid_x0 + lid_w)))
        assert gap >= d.clearance * 2 - 1e-6


# ---------------------------------------------------------------------------
# it is a container, not a brick
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("closure", ("open",) + CLOSURES)
def test_a_container_is_mostly_air(closure):
    """
    The failure the whole catalogue exists to prevent: a solid block that
    passes every geometric check. A container that is more than a quarter
    material is not hollow.
    """
    p, d, log = made(closure=closure)
    body = build_body(p, d, log)
    bb = body.val().BoundingBox()
    assert body.val().Volume() / (bb.xlen * bb.ylen * bb.zlen) < 0.25


def test_compartments_leave_dividers_of_the_wall_thickness():
    p, d, log = made(columns=3, rows=2, width_mm=200.0, depth_mm=140.0)
    body = build_body(p, d, log)
    # Six pockets in a body that is still one piece.
    assert len(body.val().Solids()) == 1
    plain, dp, lp = made(width_mm=200.0, depth_mm=140.0)
    assert body.val().Volume() > build_body(plain, dp, lp).val().Volume()


def test_compartments_in_a_round_body_are_refused_with_the_reason():
    with pytest.raises(ValueError) as caught:
        ContainerParams(shape="round", columns=3)
    assert "crescent" in str(caught.value)


def test_the_wall_is_measured_square_to_a_leaning_face():
    """
    Insetting a leaning wall by `wall` in plan gives a thinner wall than that
    measured square to the face. It is 1.5% at ten degrees and it is still
    wrong to leave in.
    """
    straight = derive(ContainerParams(taper_deg=0.0), CLEARANCE)
    leaning = derive(ContainerParams(taper_deg=10.0), CLEARANCE)
    assert leaning.inset > straight.inset


# ---------------------------------------------------------------------------
# it prints
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("closure", ("open",) + CLOSURES)
def test_every_part_is_on_the_bed_and_none_of_them_overlap(closure):
    """
    RULE 21: the print layout is its own function. Two bodies sharing space on
    the bed is a plate that cannot be sliced.
    """
    p, d, log = made(closure=closure)
    plate = build_print(p, d, log)
    solids = plate.val().Solids()
    assert len(solids) == {"open": 1, "lid": 2, "clip": 2, "magnet": 2,
                           "hinge": 3}[closure]
    assert plate.val().BoundingBox().zmin >= -0.01
    assert probe(plate)


def test_the_lid_prints_upside_down_so_its_skirt_points_up():
    """
    Not tidiness. Printed the way it sits on the box, the skirt hangs into the
    air off the underside of the flange and every pocket in it is a ceiling.
    """
    p, d, log = made(closure="magnet")
    plate = build_print(p, d, log)
    lid = sorted(plate.val().Solids(), key=lambda s: s.BoundingBox().xmin)[-1]
    # Upside down, the flange - the widest part - is at the BOTTOM.
    box = lid.BoundingBox()
    low = cq.Workplane("XY").newObject([lid]).intersect(
        cq.Workplane("XY", origin=(box.xmin, box.ymin, box.zmin))
        .box(box.xlen, box.ylen, box.zlen * 0.2, centered=False))
    high = cq.Workplane("XY").newObject([lid]).intersect(
        cq.Workplane("XY", origin=(box.xmin, box.ymin, box.zmax - box.zlen * 0.2))
        .box(box.xlen, box.ylen, box.zlen * 0.2, centered=False))
    assert low.val().Volume() > high.val().Volume() * 1.5


# ---------------------------------------------------------------------------
# the outside is not four flat faces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["ribs", "flutes", "hex", "knurl", "waves"])
def test_a_finish_changes_the_outside_without_changing_the_size(kind):
    p, d, log = made(shape="round", closure="lid", finish=kind)
    plain, dp, lp = made(shape="round", closure="lid")
    body = build_body(p, d, log)
    bare = build_body(plain, dp, lp)
    assert body.val().Volume() < bare.val().Volume()
    assert body.val().BoundingBox().xlen <= bare.val().BoundingBox().xlen + 1e-6


def test_facets_on_a_square_container_are_refused_before_anything_is_built():
    with pytest.raises(ValueError) as caught:
        ContainerParams(shape="square", finish="facets")
    assert "ROUND" in str(caught.value)


def test_a_pattern_that_would_eat_the_wall_is_refused_with_the_legal_depth():
    with pytest.raises(ValueError) as caught:
        ContainerParams(finish="ribs", wall_mm=2.4, finish_depth_mm=1.5)
    assert "0.80" in str(caught.value)


# ---------------------------------------------------------------------------
# nothing needs support
# ---------------------------------------------------------------------------

def _overhang_mm2(plate) -> float:
    """
    Downward-facing area past 45 degrees, above the first half millimetre.

    The bed's own underside is excluded: it is not an overhang, it is the
    bottom of the part.
    """
    import math

    total = 0.0
    for face in plate.val().Faces():
        try:
            normal = face.normalAt(face.Center())
        except Exception:
            continue
        centre = face.Center()
        if normal.z >= -1e-6 or centre.z < 0.6:
            continue
        if math.degrees(math.asin(min(1.0, -normal.z))) > 45.0:
            total += face.Area()
    return total


@pytest.mark.parametrize("closure", ("open",) + CLOSURES)
def test_nothing_on_the_plate_needs_support(closure):
    """
    whittle's own verifier refuses ANY unsupported area, and it is right to.
    Four things here were caught by it and nothing else:

      * the snap groove's flat roof, 545 mm2 all the way round the inside
      * the round snap bead, whose retaining face turned horizontal
      * the hinge's body web, 2 103 mm2 of slab hanging off the back wall
      * the lid's cosmetic top chamfer, which prints face down
    """
    p, d, log = made(closure=closure)
    assert _overhang_mm2(build_print(p, d, log)) == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize("kind", ["ribs", "flutes", "hex", "knurl", "waves"])
def test_no_finish_leaves_a_ceiling_where_its_band_stops(kind):
    """
    A vertical groove has no ceiling along its flanks and one at its TOP END,
    which is the part that gets forgotten: forty grooves stopping below the
    rim measured 87 mm2 of flat roof. Every band ramps back out to the wall.
    """
    p, d, log = made(shape="square", closure="lid", finish=kind)
    assert _overhang_mm2(build_print(p, d, log)) == pytest.approx(0.0, abs=0.01)


def test_the_faceted_band_ramps_back_to_the_round_section():
    p, d, log = made(shape="round", closure="lid", finish="facets", taper_deg=8.0)
    assert _overhang_mm2(build_print(p, d, log)) == pytest.approx(0.0, abs=0.01)


def test_a_feature_that_is_not_there_is_not_reported_as_zero():
    """
    `features` is measured against the nozzle. "snap bead 0.000 mm" on a box
    with no snap failed its own build for a detail that did not exist.
    """
    from whittle.build.templates.container import build as build_container

    class _Spec:
        material = "pla"

    result = build_container(ContainerParams(closure="lid"), _Spec())
    assert "snap bead" not in result.features
    assert all(v > 0 for v in result.features.values())
    assert result.derived["lid_clearance_mm"] > 0
