"""
Turning a mesh into a spec, automatically, so it becomes editable AND prints.

WHY THIS IS THE INTERESTING HALF, AND WHAT IT WAS DOING INSTEAD
---------------------------------------------------------------
A mesh is triangles: no wall to change, no rim to retype, no way to ask for it
10 mm taller. A spec is the opposite, and the gap between them is the whole
reason importing into whittle is worth more than downloading a file. Two
fitters already closed it for turned and extruded shapes.

Measured on the library as it actually stood, seven models:

    recovered a spec                1
    fitter found the shape and
      the answer was THROWN AWAY    2     <- this file
    genuinely neither turned
      nor extruded                  2
    more than one body              2

The two in the middle are the ones worth having. Both were real bowls. The
fitter measured the silhouette correctly, the vessel template refused it
because a bowl that flares past 45 degrees extrudes onto air, and the
measurement was discarded - so the object stayed triangles and nothing could
be done with it at all.

Discarding it is the wrong trade. Held to a lean that prints, the same
measurement makes a part that builds, verifies and can be edited - and the
departure is reported with its number, which is what rule 15 asks for. The
mesh is never touched and the measurement is still on disk.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from whittle.measure.revolve import LeanClamp, clamp_lean, worst_lean_deg

LIBRARY = Path(__file__).resolve().parents[1] / "library"


# ---------------------------------------------------------------------------
# the clamp itself: arithmetic, no meshes
# ---------------------------------------------------------------------------

def test_a_profile_that_already_prints_is_returned_untouched():
    """
    THE MOST IMPORTANT ONE. This runs on every turned import, and a clamp that
    quietly reshapes a bowl which was fine is far worse than one that never
    fires - the part would be wrong and nobody would have been told.
    """
    points = [[10.0, 0.0], [12.0, 10.0], [14.0, 20.0]]
    held, clamp = clamp_lean(points, 45.0)
    assert held == points
    assert not clamp.changed


def test_a_profile_that_flares_too_far_is_held_to_exactly_the_limit():
    points = [[10.0, 0.0], [40.0, 10.0], [80.0, 20.0]]
    assert worst_lean_deg(points) > 45.0
    held, clamp = clamp_lean(points, 45.0)
    assert worst_lean_deg(held) == pytest.approx(45.0, abs=1e-6)
    assert clamp.changed


def test_only_the_segments_that_break_the_rule_move():
    """
    A bowl that flares only near its rim keeps its whole body. Moving the lot
    would be reshaping an object to fix its last centimetre.
    """
    points = [[20.0, 0.0], [22.0, 10.0], [24.0, 20.0], [60.0, 25.0]]
    held, _ = clamp_lean(points, 45.0)
    assert held[:3] == points[:3]
    assert held[3][0] < points[3][0]


def test_the_clamp_walks_upward_so_one_pass_leaves_nothing_over_the_limit():
    """
    Each cap is measured against the point below AS ALREADY CAPPED. Capping
    every point against the ORIGINAL point below it leaves a profile that is
    still illegal wherever two bad segments run together.
    """
    points = [[5.0, 0.0], [50.0, 5.0], [95.0, 10.0], [140.0, 15.0]]
    held, _ = clamp_lean(points, 45.0)
    assert worst_lean_deg(held) <= 45.0 + 1e-6


def test_a_step_that_goes_down_or_nowhere_is_left_alone():
    """A profile is measured bottom-up, so a flat step is a step and not a fold."""
    points = [[10.0, 0.0], [30.0, 0.0], [25.0, 5.0]]
    held, _ = clamp_lean(points, 45.0)
    assert held == points


def test_the_departure_is_reported_with_its_numbers():
    """
    RULE 15: every deliberate departure carries its numeric factor. A note
    saying "adjusted for printability" is not a report, it is an apology.
    """
    held, clamp = clamp_lean([[10.0, 0.0], [80.0, 20.0]], 45.0)
    why = clamp.why()
    assert "%.1f" % clamp.was_deg in why
    assert "45" in why
    assert "mm" in why and "%" in why
    # And it says where the untouched measurement still is.
    assert "import.json" in why


def test_a_profile_too_short_to_lean_is_not_an_error():
    held, clamp = clamp_lean([[10.0, 0.0]], 45.0)
    assert held == [[10.0, 0.0]]
    assert not clamp.changed


def test_the_lean_is_measured_the_way_the_template_measures_it():
    """
    THE SAME ARITHMETIC, deliberately. This decides whether the vessel template
    will accept a profile, so measuring it any other way here is a second
    opinion about somebody else's rule - and the clamp would then hand over
    something still refused.
    """
    from whittle.build.templates.vessel import VesselParams

    points = [[10.0, 0.0], [40.0, 10.0], [70.0, 20.0]]
    held, _ = clamp_lean(points, 45.0)

    made = VesselParams(
        profile="custom",
        profile_points=[(r, z) for r, z in held],
        outer_dia_mm=2 * max(r for r, _ in held),
        height_mm=held[-1][1] - held[0][1],
    )
    assert made.worst_lean_deg() <= 45.0 + 1e-6


# ---------------------------------------------------------------------------
# end to end, on the models that were actually being thrown away
# ---------------------------------------------------------------------------

def _mesh(name: str):
    path = LIBRARY / name / "out" / ("%s.stl" % name)
    if not path.is_file():
        pytest.skip("%s is not in the library on this machine" % name)
    trimesh = pytest.importorskip("trimesh")
    return trimesh.load(path, force="mesh")


@pytest.mark.parametrize("name", ["turned_pot", "pot_straight"])
def test_a_bowl_that_flares_too_far_now_comes_back_as_an_editable_spec(name, tmp_path):
    """
    Both of these measured correctly and were discarded. The recovered spec is
    what makes the object editable, and editable is the product.
    """
    from whittle import imports

    part = imports.ImportedPart(name=name, directory=tmp_path)
    imports._try_recover_spec(part, _mesh(name), tmp_path)

    assert part.editable, part.fit_note
    assert (tmp_path / "spec.yaml").is_file()
    # And it SAYS it was held, with the figure.
    assert part.departures and "degrees from vertical" in part.departures[0]


@pytest.mark.parametrize("name", ["turned_pot", "pot_straight"])
def test_the_recovered_spec_builds_and_passes_verification(name, tmp_path):
    """
    "SO THAT THEY BECOME PRINTABLE" is the point of the whole exercise. A spec
    that is written and then will not build is worse than no spec: it claims
    the object was understood.
    """
    from whittle import api, imports

    part = imports.ImportedPart(name=name, directory=tmp_path)
    imports._try_recover_spec(part, _mesh(name), tmp_path)
    assert part.editable

    # api.build runs the verify gate and raises when a part does not pass it.
    api.build(tmp_path / "spec.yaml", out_dir=tmp_path)
    assert next(tmp_path.rglob("*.stl"), None) is not None


@pytest.mark.parametrize("name", ["turned_pot", "pot_straight"])
def test_the_recovered_part_is_still_the_shape_that_was_measured(name, tmp_path):
    """
    A spec that prints but is not the object is a different failure, not a fix.
    The envelope has to survive: this is a bowl held to a printable lean, not
    a bowl replaced by a cylinder.
    """
    from whittle import api, imports

    mesh = _mesh(name)
    part = imports.ImportedPart(name=name, directory=tmp_path)
    imports._try_recover_spec(part, mesh, tmp_path)
    api.build(tmp_path / "spec.yaml", out_dir=tmp_path)

    trimesh = pytest.importorskip("trimesh")
    rebuilt = trimesh.load(next(tmp_path.rglob("*.stl")), force="mesh")
    for got, wanted in zip(rebuilt.extents, mesh.extents):
        # Within a millimetre on height and width. The clamp only ever takes
        # material off, so it can be under and never over.
        assert got <= wanted + 1.0
        assert got > wanted * 0.5


def test_a_shape_that_is_neither_turned_nor_extruded_is_still_refused(tmp_path):
    """
    The clamp must not become a way to fit a bowl to a teapot. A shape the
    fitters reject is rejected before any of this runs, and it stays rejected -
    a confident wrong answer is worse than none.
    """
    from whittle import imports

    part = imports.ImportedPart(name="extruder-cable-clip", directory=tmp_path)
    imports._try_recover_spec(part, _mesh("extruder-cable-clip"), tmp_path)
    assert not part.editable
    assert not (tmp_path / "spec.yaml").exists()
    assert "not a turned shape" in part.fit_note
