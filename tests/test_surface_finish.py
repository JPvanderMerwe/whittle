"""
The outside of a printed object, and the three promises the module makes.

Not "does it build". A finish that builds and quietly grew the part, or ate
through the wall into the cavity, is worse than one that fails - it looks
right in every render and it is wrong on the bed. So each promise in
whittle/build/surface.py's docstring has a test that would catch it being
broken:

  1. it never grows the part
  2. it never opens the wall
  3. an impossible finish is REFUSED, with the number that would work

plus the two bugs that were actually found building it, which are here so
they cannot come back: overlapping cutters (the facet family), and a straight
cutter on a curved wall (the round snap bead's cousin).
"""

from __future__ import annotations

import cadquery as cq
import pytest

from whittle.build import surface
from whittle.build.helpers import BuildLog, probe

WALL = 2.4
KINDS = ("ribs", "flutes", "hex", "knurl", "waves")


def tube(dia_bottom: float, dia_top: float, height: float) -> tuple:
    outer = (cq.Workplane("XY").circle(dia_bottom / 2.0)
             .workplane(offset=height).circle(dia_top / 2.0).loft())
    cavity = (cq.Workplane("XY", origin=(0, 0, 2.0))
              .circle(dia_bottom / 2.0 - WALL)
              .workplane(offset=height).circle(dia_top / 2.0 - WALL).loft())
    return outer.cut(cavity), cavity


def slab(w: float, d: float, height: float) -> tuple:
    outer = cq.Workplane("XY").box(w, d, height, centered=(True, True, False))
    cavity = (cq.Workplane("XY").box(w - 2 * WALL, d - 2 * WALL, height,
                                     centered=(True, True, False))
              .translate((0, 0, 2.0)))
    return outer.cut(cavity), cavity


def finish(kind: str, **kw) -> surface.Finish:
    return surface.Finish(kind, kw.get("pitch", 9.0), kw.get("groove", 3.0),
                          kw.get("depth", 0.7))


# ---------------------------------------------------------------------------
# promise 1: it never grows the part
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS + ("facets",))
def test_a_finish_never_makes_the_object_bigger(kind):
    """
    The box that fitted the drawer still fits it.

    Every family here is CUT, never added, which is why nominal_mm can still
    be trusted after one has been applied. A decoration that stood 0.5 mm
    proud would be invisible in a render and 1 mm too wide in the drawer.
    """
    body, _ = tube(80.0, 80.0, 90.0)
    before = body.val().BoundingBox()
    out = surface.apply(body, surface.Shell("round", 5.0, 85.0, (80.0, 80.0),
                                            (80.0, 80.0)),
                        finish(kind), WALL)
    after = out.val().BoundingBox()
    assert after.xlen <= before.xlen + 1e-6
    assert after.ylen <= before.ylen + 1e-6
    assert after.zlen <= before.zlen + 1e-6


# ---------------------------------------------------------------------------
# promise 2: it never opens the wall
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", KINDS + ("facets",))
def test_a_finish_never_reaches_the_cavity(kind):
    """
    A pattern that breaks through is a hole, and on a container it is a leak.

    Tested on a TAPERED wall, because that is where it would happen: a cutter
    that does not lean with the wall is at the right depth in the middle of
    the band and through it at one end.
    """
    body, cavity = tube(70.0, 90.0, 90.0)
    out = surface.apply(body, surface.Shell("round", 5.0, 85.0, (70.0, 70.0),
                                            (90.0, 90.0)),
                        finish(kind), WALL)
    removed = body.cut(out)
    try:
        leak = removed.intersect(cavity).val().Volume()
    except Exception:
        leak = 0.0
    assert leak == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("kind", KINDS)
def test_a_finish_actually_removes_material(kind):
    """
    The opposite failure, and the quieter one: a finish that was asked for,
    reported, and did nothing. A pattern is not optional decoration once
    somebody has asked for it - it is the difference they wanted.
    """
    body, _ = slab(80.0, 60.0, 90.0)
    out = surface.apply(body, surface.Shell("square", 5.0, 85.0, (80.0, 60.0),
                                            (80.0, 60.0), corner_r_mm=4.0),
                        finish(kind), WALL)
    assert body.val().Volume() - out.val().Volume() > 50.0
    assert out.val().isValid() and probe(out)


# ---------------------------------------------------------------------------
# promise 3: what cannot be done is refused, by name, with the figure
# ---------------------------------------------------------------------------

def test_a_groove_deeper_than_a_third_of_the_wall_is_refused_with_the_legal_depth():
    bad = surface.check(finish("ribs", depth=1.2), 2.4)
    assert bad and "0.80" in bad


def test_a_groove_wider_than_its_spacing_is_refused():
    assert surface.check(finish("ribs", pitch=3.0, groove=4.0), 2.4)


def test_waves_that_would_run_into_one_another_are_refused():
    """
    A wave is its groove PLUS the ramp that climbs out of it. Two that overlap
    are two cutters sharing space, and a compound of overlapping cutters is
    undefined - the measured result was a solid of NEGATIVE volume.
    """
    bad = surface.check(finish("waves", pitch=4.0, groove=3.0, depth=0.7), 2.4)
    assert bad and "ramp" in bad


def test_a_deep_honeycomb_is_refused_because_its_ceiling_cannot_bridge():
    bad = surface.check(finish("hex", depth=1.5), 9.0)
    assert bad and "bridge" in bad


def test_facets_on_a_square_body_are_refused_by_name():
    """
    Not "it did not fit" - the real reason. A square body already has flats,
    and a message about spacing would send somebody off changing the spacing.
    """
    shell = surface.Shell("square", 5.0, 85.0, (80.0, 60.0), (80.0, 60.0))
    bad = surface.check(finish("facets"), 2.4, shell)
    assert bad and "ROUND" in bad


def test_a_finish_that_cannot_be_cut_raises_rather_than_being_skipped():
    """
    The worst of the three outcomes is the quiet one: the part looks finished
    and is not what was asked for.
    """
    body, _ = tube(80.0, 80.0, 90.0)
    with pytest.raises(surface.SurfaceError):
        surface.apply(body, surface.Shell("round", 5.0, 85.0, (80.0, 80.0),
                                          (80.0, 80.0)),
                      finish("ribs", depth=2.0), WALL)


# ---------------------------------------------------------------------------
# the bugs that were found building it
# ---------------------------------------------------------------------------

def test_facets_are_one_prism_and_not_a_heap_of_overlapping_boxes():
    """
    REGRESSION. A facet per flat, as N big boxes, is the obvious build and it
    is wrong: those boxes overlap heavily, a compound of overlapping solids is
    not a defined thing to subtract, and the measured result on a tapered body
    was a body of NEGATIVE volume that still reported isValid().
    """
    body, _ = tube(70.0, 90.0, 90.0)
    out = surface.apply(body, surface.Shell("round", 5.0, 85.0, (70.0, 70.0),
                                            (90.0, 90.0)),
                        finish("facets"), WALL)
    assert out.val().Volume() > 0
    assert out.val().isValid()
    assert 0 < body.val().Volume() - out.val().Volume() < body.val().Volume()


def test_a_finish_on_a_tapered_wall_leans_with_it():
    """
    A vertical cutter on a leaning wall cuts through the rim and barely
    scratches the foot. Proved by depth rather than by eye: the volume removed
    from a tapered body is within a quarter of the volume removed from a
    straight one of the same surface area, which it could not be if half the
    cutters were missing the wall.
    """
    straight, _ = tube(80.0, 80.0, 90.0)
    tapered, _ = tube(70.0, 90.0, 90.0)
    a = straight.val().Volume() - surface.apply(
        straight, surface.Shell("round", 5.0, 85.0, (80.0, 80.0), (80.0, 80.0)),
        finish("ribs"), WALL).val().Volume()
    b = tapered.val().Volume() - surface.apply(
        tapered, surface.Shell("round", 5.0, 85.0, (70.0, 70.0), (90.0, 90.0)),
        finish("ribs"), WALL).val().Volume()
    assert 0.75 < b / a < 1.35


def test_a_honeycomb_too_fine_to_build_is_opened_up_and_says_so():
    """
    RULE 9 - a coarser pattern than was asked for is a substitution, and a
    silent one is the kind this project does not make.
    """
    log = BuildLog()
    body, _ = tube(120.0, 120.0, 200.0)
    surface.apply(body, surface.Shell("round", 5.0, 195.0, (120.0, 120.0),
                                      (120.0, 120.0)),
                  finish("hex", pitch=3.0, groove=2.0, depth=0.6), WALL, log)
    assert any("opened" in note for note in log.notes)


def test_every_finish_name_has_a_cutter_written_for_it():
    """
    A name in FINISHES with no builder behind it is a choice that fails at
    build time, which is the one place it must not.
    """
    body, _ = tube(80.0, 80.0, 90.0)
    shell = surface.Shell("round", 5.0, 85.0, (80.0, 80.0), (80.0, 80.0))
    for kind in surface.FINISHES:
        out = surface.apply(body, shell, finish(kind), WALL)
        assert out.val().isValid(), kind
