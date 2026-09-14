"""
Ingest: the front door of the product. Build plan v8 sections 5 and 10.

M1's acceptance is written down in the plan: "a Meshy GLB and a Printables STL
both load, repair cleanly, and produce an accurate problem list." That is the
last test in this file, and the rest are the pieces it stands on.

Every calibration figure quoted in a comment here was measured, not chosen.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh

from whittle.ingest import (
    UnsupportedFormat,
    check,
    detect_format,
    guess_units,
    ingest,
    repair_mesh,
)
from whittle.ingest.gate import THIN_SURFACE_FAIL, THIN_SURFACE_WARN, measure_thickness

ROOT = Path(__file__).resolve().parents[1]
STL = ROOT / "reference" / "vent_louvre.stl"


# ---------------------------------------------------------------------------
# formats
# ---------------------------------------------------------------------------


def test_a_format_we_cannot_read_says_so_by_name():
    """
    whittle/imports.py accepts `.3mf` and trimesh 5.0 cannot read one, so that
    import has never worked - it fails somewhere inside the loader with
    whatever message the library happens to produce. Listing a format we
    cannot read is worse than not listing it: the user takes the file we told
    them to take and it breaks.
    """
    with pytest.raises(UnsupportedFormat) as caught:
        detect_format("model.3mf")
    message = str(caught.value)
    assert "3MF" in message
    assert "STL or STEP" in message, "the refusal has to say what to bring"


def test_the_format_says_what_having_it_costs():
    """v8 section 5: "Format decides capability", and the user is told at upload."""
    stl = detect_format("thing.stl")
    assert stl.topology == "mesh"
    assert stl.carries_units is False
    assert "STEP" in stl.advice

    step = detect_format("thing.step")
    assert step.topology == "brep"
    assert step.carries_units is True


def test_a_file_with_no_extension_is_refused_usefully():
    with pytest.raises(UnsupportedFormat) as caught:
        detect_format("somefile")
    assert ".stl" in str(caught.value)


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------


def test_a_format_that_states_its_units_is_not_guessed_at():
    """
    glTF measures in metres by specification. That is the format's contract,
    not an inference from the numbers, so it is reported as certain.
    """
    guess = guess_units(0.086, "m")
    assert guess.certain
    assert guess.scale_to_mm == 1000.0
    assert "86" in guess.reason


def test_an_unlabelled_file_is_guessed_and_called_a_guess():
    """
    An STL is coordinates with no statement of what they are. The same file is
    a 40 mm bracket and a 4 cm bracket, and nothing in it separates them -
    CLAUDE.md 29 says whittle does not substitute a plausible number silently.
    """
    guess = guess_units(86.0, None)
    assert guess.units == "mm"
    assert guess.assumed is True
    assert "check it" in guess.reason
    # The runners-up come with it, so the user can pick the right one.
    assert any(unit == "cm" for unit, _ in guess.alternatives)


def test_a_file_written_in_metres_reads_as_metres():
    """0.086 across is not an 86-micron object. Nobody prints one of those."""
    guess = guess_units(0.086, None)
    assert guess.units == "m"
    assert abs(guess.scale_to_mm - 1000.0) < 1e-9


def test_a_size_that_is_impossible_in_every_unit_says_unknown():
    guess = guess_units(1e7, None)
    assert guess.units == "unknown"
    assert guess.scale_to_mm == 1.0


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------


def _unwelded(mesh):
    """A mesh with every triangle carrying its own copy of its corners."""
    verts = mesh.triangles.reshape(-1, 3)
    faces = np.arange(len(verts)).reshape(-1, 3)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def test_repair_seals_a_mesh_without_moving_the_surface():
    """
    THE COMMONEST FAULT IN A DOWNLOAD, AND IT IS NOT A FAULT IN THE SHAPE.
    STL has no way to say two triangles share a corner, so each carries its
    own copy and every topology test reads the mesh as full of holes while it
    looks perfect.

    The shape must not move. That is what makes this repair and not editing -
    whittle/imports.py refuses to repair on the grounds that the thing in the
    library would no longer be the thing downloaded, and the answer to that
    objection is that the volume is identical to the last decimal.
    """
    box = trimesh.creation.box((20, 20, 20))
    broken = _unwelded(box)
    assert not broken.is_watertight

    result = repair_mesh(broken)

    assert result.watertight
    assert result.changed
    assert abs(result.mesh.volume - 8000.0) < 1e-6, "the repair moved the surface"
    assert any("welded" in step.name for step in result.steps)


def test_the_original_survives_the_repair():
    """v8 section 5 step 3: "allow undo of the repair itself"."""
    broken = _unwelded(trimesh.creation.box((20, 20, 20)))
    result = repair_mesh(broken)

    assert result.watertight
    back = result.undo()
    assert not back.is_watertight, "undo did not give back the original"
    assert len(back.vertices) == len(broken.vertices)


def test_every_change_is_written_down():
    """
    A repair nobody can see is the thing imports.py was protecting against.
    Each step names what it did and how many of them there were.
    """
    broken = _unwelded(trimesh.creation.box((20, 20, 20)))
    dead = trimesh.Trimesh(vertices=np.zeros((3, 3)),
                           faces=np.array([[0, 1, 2]]), process=False)
    result = repair_mesh(trimesh.util.concatenate([broken, dead]))

    assert result.steps
    for step in result.steps:
        assert step.count > 0
        assert step.detail, "a step with no explanation is a silent change"
    assert "welded" in result.summary()


def test_a_sound_mesh_is_left_alone():
    result = repair_mesh(trimesh.creation.box((10, 10, 10)))
    assert not result.changed
    assert result.summary() == "nothing needed repairing"


# ---------------------------------------------------------------------------
# thickness, which is the check nobody else gives them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("thickness_mm", [0.6, 2.0])
def test_a_slab_measures_its_own_thickness(thickness_mm):
    """
    The shrinking ball: the largest sphere touching the surface at a point and
    containing no other part of it. On a slab that sphere is exactly half the
    thickness.
    """
    slab = trimesh.creation.box((40, thickness_mm, 40))
    measured = float(np.median(measure_thickness(slab)))
    assert abs(measured - thickness_mm) < thickness_mm * 0.15, (
        "a %.1f mm slab measured %.3f mm" % (thickness_mm, measured))


def test_a_solid_object_is_not_called_thin():
    """
    THE FALSE POSITIVE THAT MATTERS. Near a convex edge the largest inscribed
    sphere really does shrink to nothing - that is the medial axis of a cube,
    not a measurement error - so a solid object always reads a few percent
    thin. Telling somebody their solid cylinder has sub-nozzle walls would
    destroy their trust in every other number on the screen.
    """
    for solid in (trimesh.creation.box((20, 20, 20)),
                  trimesh.creation.cylinder(radius=6, height=30),
                  trimesh.creation.icosphere(subdivisions=3, radius=10)):
        thin = float((measure_thickness(solid) < 0.8).mean())
        assert thin < THIN_SURFACE_WARN, (
            "a solid object read %.1f%% thin, which would be reported" % (thin * 100))


def test_a_model_that_is_mostly_thinner_than_the_nozzle_fails():
    report = check(trimesh.creation.box((40, 0.6, 40)),
                   nozzle_mm=0.4, bed_mm=(220, 220, 250))
    walls = [f for f in report.findings if f.rule == "wall thickness"]
    assert walls and walls[0].severity == "fail", report.as_text()
    assert "0.80 mm minimum" in walls[0].detail
    assert report.measurements["thin_surface_fraction"] >= THIN_SURFACE_FAIL


def test_a_thin_fin_on_a_thick_body_is_warned_about():
    body = trimesh.creation.icosphere(subdivisions=4, radius=30)
    fin = trimesh.creation.box((40, 0.6, 40)).apply_translation((0, 0, 50))
    report = check(trimesh.util.concatenate([body, fin]),
                   nozzle_mm=0.4, bed_mm=(220, 220, 250))

    walls = [f for f in report.findings if f.rule == "wall thickness"]
    assert walls, report.as_text()
    assert walls[0].severity == "warn"
    # And it says roughly the right number rather than just "thin".
    assert 0.4 < report.measurements["thickness_p5_mm"] < 1.0


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


def test_loose_fragments_are_found():
    """
    Generated meshes are full of stray shells. They print as specks welded to
    the model and are invisible until they do. Calibrated on a 0.4 mm speck
    beside a 60 mm body, which is 0.7% of it and was missed at the first
    threshold.
    """
    body = trimesh.creation.icosphere(subdivisions=3, radius=30)
    speck = trimesh.creation.box((0.4, 0.4, 0.4)).apply_translation((60, 0, 0))
    report = check(trimesh.util.concatenate([body, speck]),
                   nozzle_mm=0.4, bed_mm=(220, 220, 250))

    fragments = [f for f in report.findings if f.rule == "loose fragments"]
    assert fragments, report.as_text()
    assert report.measurements["debris_shells"] == 1
    assert fragments[0].fix == "remove_floaters"


def test_no_flat_base_is_reported_with_the_way_out():
    ball = trimesh.creation.icosphere(subdivisions=3, radius=20)
    report = check(ball, nozzle_mm=0.4, bed_mm=(220, 220, 250))

    base = [f for f in report.findings if f.rule == "flat base"]
    assert base, report.as_text()
    assert "flatten_base" in base[0].fix


def test_too_big_for_the_bed_is_a_failure_with_a_suggestion():
    slab = trimesh.creation.box((300, 40, 40))
    report = check(slab, nozzle_mm=0.4, bed_mm=(220, 220, 250))

    size = [f for f in report.findings if f.rule == "bed size"]
    assert size, report.as_text()
    assert not report.printable
    assert "cut_plane" in size[0].fix


def test_every_finding_names_a_measured_value():
    """
    v8 section 10: name the violated rule and the responsible parameter.
    "Thin walls detected" is a complaint; a number is a finding.
    """
    body = trimesh.creation.icosphere(subdivisions=3, radius=30)
    speck = trimesh.creation.box((0.4, 0.4, 0.4)).apply_translation((60, 0, 0))
    report = check(trimesh.util.concatenate([body, speck]),
                   nozzle_mm=0.4, bed_mm=(220, 220, 250))

    assert report.findings
    for finding in report.findings:
        assert finding.severity in ("fail", "warn")
        assert finding.rule
        assert any(ch.isdigit() for ch in finding.detail), (
            "%r carries no measured value" % finding.detail)


# ---------------------------------------------------------------------------
# M1's own acceptance, as the plan words it
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not STL.is_file(), reason="no reference STL in this checkout")
def test_a_glb_and_an_stl_both_land_at_the_same_real_size(tmp_path):
    """
    M1 IS DONE WHEN: "a Meshy GLB and a Printables STL both load, repair
    cleanly, and produce an accurate problem list."

    The two files describe the identical object, one in metres as a generator
    exports it and one in millimetres as a download arrives. Landing at the
    same size is the whole of unit handling working: the GLB is scaled from
    its own declared units and the STL is inferred and marked as assumed.
    """
    metres = trimesh.load(STL, force="mesh")
    metres.apply_scale(0.001)
    glb = tmp_path / "generated.glb"
    metres.export(glb)

    from_stl = ingest(STL)
    from_glb = ingest(glb)

    stl_size = from_stl.mesh.bounds[1] - from_stl.mesh.bounds[0]
    glb_size = from_glb.mesh.bounds[1] - from_glb.mesh.bounds[0]
    assert np.allclose(stl_size, glb_size, atol=0.01), (
        "the same object came out %s from the STL and %s from the GLB"
        % (stl_size, glb_size))
    assert 80 < stl_size[0] < 90, "not in millimetres: %s" % stl_size

    # The GLB knows its units; the STL admits it is guessing.
    assert from_glb.units.certain
    assert from_stl.units.assumed

    # Both produce a real report rather than an empty one.
    for result in (from_stl, from_glb):
        assert result.report.findings, "no problems found at all, which is a bug"
        assert "triangles" in result.summary()


def test_the_surface_probe_gives_the_same_answer_bucketed_or_not():
    """
    CLAUDE.md 30: keep the existing behaviour as the default and prove
    equivalence with a test.

    surface_below tested every query point against every triangle - correct,
    and fine for the meshes this project BUILDS at three to forty thousand
    triangles. v8 points it at downloads: a 327,680-triangle model spent
    240.84 seconds in that one function, out of a 267-second printability
    gate whose every other check totalled 0.3 seconds.

    A spatial grid fixed it. The arithmetic per candidate triangle is
    untouched, so the answer must be untouched too - not close, identical.
    """
    from whittle.verify import probe

    ball = trimesh.creation.icosphere(subdivisions=4, radius=30)
    centres = ball.triangles_center
    points, tops = centres[:, [0, 1]], centres[:, 2]

    direct = np.array(probe.surface_below(ball, points, tops), dtype=float)

    saved = probe.DIRECT_PRODUCT
    probe.DIRECT_PRODUCT = 0            # force the grid path on a small mesh
    try:
        bucketed = np.array(probe.surface_below(ball, points, tops), dtype=float)
    finally:
        probe.DIRECT_PRODUCT = saved

    assert np.array_equal(np.isnan(direct), np.isnan(bucketed))
    assert np.array_equal(direct[~np.isnan(direct)],
                          bucketed[~np.isnan(bucketed)])


def test_a_heavy_model_gets_a_proxy_to_edit_against():
    """
    THE PROXY HAD NEVER BEEN BUILT. simplify_quadric_decimation needs
    `fast_simplification`, which is not installed, and a bare `except` turned
    that into "no proxy" - silently, for exactly the models a proxy exists
    for. It was the third time in one sitting that a missing optional package
    disappeared into an except: `rtree` had already cost the thin-wall check
    twice.
    """
    from whittle.ingest.pipeline import _make_proxy

    heavy = trimesh.creation.icosphere(subdivisions=7, radius=60)
    assert len(heavy.faces) > 300_000

    proxy = _make_proxy(heavy, 300_000)
    assert proxy is not None, "a 327k-triangle mesh got no proxy"
    assert proxy.triangles <= 300_000
    assert proxy.triangles > 1000, "the proxy collapsed to nothing"

    # Under the budget there is nothing to gain, so there is no proxy.
    light = trimesh.creation.icosphere(subdivisions=3, radius=60)
    assert _make_proxy(light, 300_000) is None
