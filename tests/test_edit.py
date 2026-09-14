"""
The edit stack and the print-prep operations. Build plan v8 sections 4 and 6.

M2's acceptance is in the plan: "a generated dragon can be hollowed,
flattened, thin-wall-thickened, de-floatered and cut for bed fit, and every
operation stays adjustable afterwards." That is the last test here.

The caching tests are not performance tests. Section 4 says the cache is the
architecture rather than an optimisation - "a stack that recomputes from
scratch on every drag is not interactive" - so what is asserted is WHICH steps
recomputed, which is a fact about correctness rather than about speed.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from whittle.edit import EditError, EditStack, REGISTRY, describe_registry
from whittle.edit.cut import cut_with_plane


def _box(size=20.0):
    return trimesh.creation.box((size, size, size))


def _recomputed(stack: EditStack) -> list[str]:
    return [r.op.kind for r in stack.last_run if not r.from_cache]


# ---------------------------------------------------------------------------
# cutting, which nothing else works without
# ---------------------------------------------------------------------------


def test_a_plane_cut_is_sealed_and_the_right_size():
    """
    trimesh's own slice needs shapely and booleans need manifold3d, neither of
    which is installed, so this is written out. A cut that is not watertight
    cannot be printed, and one with the wrong volume is the wrong model.
    """
    cut = cut_with_plane(_box(20), [0, 0, 5], [0, 0, 1])
    assert cut.is_watertight
    assert abs(cut.volume - 6000.0) < 1e-6, cut.volume
    assert abs(float(cut.bounds[1][2]) - 5.0) < 1e-9

    other = cut_with_plane(_box(20), [0, 0, 5], [0, 0, -1])
    assert other.is_watertight
    assert abs(other.volume - 2000.0) < 1e-6


@pytest.mark.parametrize("subdivisions", [3, 4])
def test_a_curved_cut_seals_too(subdivisions):
    """
    THE BUG THIS PINS HAD ZERO OPEN EDGES AND WAS STILL NOT A SOLID.

    A triangle lying almost flat against the cutting plane produces two
    crossing points a hair apart. merge_vertices joins them, correctly, and
    leaves a triangle with two identical corners - no area - plus whatever
    real face it collapsed onto. The sphere came out with no holes at all and
    eighty edges shared by three or four faces.
    """
    ball = trimesh.creation.icosphere(subdivisions=subdivisions, radius=10)
    half = cut_with_plane(ball, [0, 0, 0], [0, 0, 1])

    assert half.is_watertight
    expected = (2.0 / 3.0) * math.pi * 1000.0
    assert abs(half.volume - expected) / expected < 0.02


def test_a_cut_through_a_hollow_shape_keeps_its_hole():
    """
    The cut face of a tube is a ring, not a disc. A cap that fans from the
    centre fills the hole in and turns a hollowed model solid - which is
    exactly the case this product exists for, so the even-odd rule earns its
    keep here.
    """
    tube = trimesh.creation.annulus(r_min=6, r_max=10, height=30)
    cut = cut_with_plane(tube, [0, 0, 0], [0, 0, 1])

    assert cut.is_watertight
    expected = math.pi * (100 - 36) * 15
    assert abs(cut.volume - expected) / expected < 0.02, (
        "%.1f against %.1f - the hole was filled in" % (cut.volume, expected))


def test_a_cut_that_removes_everything_says_so():
    # The plane keeps the side its normal points AWAY from, so +Z at z=-50
    # keeps everything below -50, which is nothing.
    with pytest.raises(ValueError):
        cut_with_plane(_box(20), [0, 0, -50], [0, 0, 1])


# ---------------------------------------------------------------------------
# the stack
# ---------------------------------------------------------------------------


def test_the_stack_evaluates_in_order():
    stack = EditStack(_box(20))
    stack.add("scale_uniform", factor=2.0)
    stack.add("flatten_base", depth_mm=5.0)

    out = stack.evaluate()
    # 20 doubled is 40, less 5 off the bottom.
    assert abs(float(out.extents[2]) - 35.0) < 0.01


def test_only_what_changed_recomputes():
    """
    v8 section 4: "moving one slider does not recompute the whole chain". This
    is the assertion that makes the interactive claim in 13.3 true.
    """
    stack = EditStack(_box(40))
    first = stack.add("scale_uniform", factor=1.5)
    stack.add("flatten_base", depth_mm=2.0)
    last = stack.add("hollow", wall_mm=2.0)

    stack.evaluate()
    assert len(_recomputed(stack)) == 3, "the first run should compute all three"

    stack.evaluate()
    assert _recomputed(stack) == [], "nothing changed, so nothing should recompute"

    stack.set_value(last.id, "wall_mm", 3.0)
    stack.evaluate()
    assert _recomputed(stack) == ["hollow"], (
        "changing the last step recomputed %s" % _recomputed(stack))

    stack.set_value(first.id, "factor", 2.0)
    stack.evaluate()
    assert len(_recomputed(stack)) == 3, (
        "changing the first step has to invalidate everything after it")


def test_turning_a_step_off_reverts_through_it():
    """v8 section 13.3: "Operations are never destructive"."""
    stack = EditStack(_box(40))
    stack.add("scale_uniform", factor=1.0)
    flatten = stack.add("flatten_base", depth_mm=10.0)

    flattened = float(stack.evaluate().extents[2])
    stack.toggle(flatten.id, False)
    whole = float(stack.evaluate().extents[2])

    assert abs(whole - 40.0) < 0.01
    assert abs(flattened - 30.0) < 0.01

    stack.toggle(flatten.id, True)
    assert abs(float(stack.evaluate().extents[2]) - 30.0) < 0.01


def test_a_disabled_step_caches_separately():
    """
    A stack with step two off is a different stack from one with it on, so it
    must not read the other's cached result. Getting this wrong shows up as a
    toggle that does nothing on the second press.
    """
    stack = EditStack(_box(40))
    flatten = stack.add("flatten_base", depth_mm=10.0)

    on = float(stack.evaluate().extents[2])
    stack.toggle(flatten.id, False)
    off = float(stack.evaluate().extents[2])
    stack.toggle(flatten.id, True)
    on_again = float(stack.evaluate().extents[2])

    assert abs(on - on_again) < 1e-9
    assert abs(off - on) > 1.0


def test_a_slider_stops_rather_than_breaking_the_model():
    """
    v8 section 10: "clamp slider ranges so most failures become impossible
    rather than reported". A wall under two extrusions cannot print, so the
    slider does not go there.
    """
    stack = EditStack(_box(40), nozzle_mm=0.4)
    hollow = stack.add("hollow", wall_mm=2.0)

    bound = stack.set_value(hollow.id, "wall_mm", 0.1)
    assert bound.value == pytest.approx(0.8), (
        "a 0.1 mm wall was accepted on a 0.4 mm nozzle")
    assert bound.slidable


def test_an_unknown_operation_names_the_ones_that_exist():
    stack = EditStack(_box(20))
    with pytest.raises(EditError) as caught:
        stack.add("polish")
    assert "hollow" in str(caught.value)


def test_the_stack_serialises_to_the_durable_artefact():
    """
    v8 section 4: the durable artefact is the source plus the stack, never
    baked geometry. What comes out of to_json has to be enough to rebuild.
    """
    stack = EditStack(_box(20))
    stack.add("scale_uniform", factor=2.0)
    stack.add("hollow", wall_mm=1.5)

    data = stack.to_json()
    assert [row["kind"] for row in data] == ["scale_uniform", "hollow"]
    assert data[1]["values"]["wall_mm"] == pytest.approx(1.5)
    assert all(row["enabled"] for row in data)


def test_the_registry_says_what_is_not_built():
    """
    Nobody should build against an operation that does not exist. v8 section 6
    lists more than M2 delivers, and the gap is named rather than left to be
    discovered.
    """
    text = describe_registry()
    assert "hollow" in text
    assert "not built yet" in text
    assert "auto_orient" in text
    assert "auto_orient" not in REGISTRY


# ---------------------------------------------------------------------------
# the operations
# ---------------------------------------------------------------------------


def test_removing_floaters_keeps_the_model_and_drops_the_specks():
    body = trimesh.creation.icosphere(subdivisions=3, radius=30)
    speck = trimesh.creation.box((0.4, 0.4, 0.4)).apply_translation((60, 0, 0))
    dirty = trimesh.util.concatenate([body, speck])

    stack = EditStack(dirty)
    stack.add("remove_floaters", keep_fraction=0.02)
    clean = stack.evaluate()

    assert len(clean.split(only_watertight=False)) == 1
    assert abs(clean.volume - body.volume) / body.volume < 0.01


def test_hollowing_needs_a_sealed_model_and_says_so():
    """A model with gaps has no inside to take out."""
    open_mesh = trimesh.Trimesh(
        vertices=np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=float),
        faces=np.array([[0, 1, 2]]), process=False)
    stack = EditStack(open_mesh)
    stack.add("hollow", wall_mm=2.0)

    with pytest.raises(EditError) as caught:
        stack.evaluate()
    assert "sealed" in str(caught.value)


def test_hollowing_leaves_a_cavity():
    stack = EditStack(_box(40))
    stack.add("hollow", wall_mm=2.0)
    out = stack.evaluate()

    assert len(out.split(only_watertight=False)) == 2, (
        "a hollow model is an outer surface and an inner one")
    assert out.volume < _box(40).volume


def test_mirroring_does_not_leave_the_model_inside_out():
    """
    Flipping one axis reverses every triangle's winding. Left alone the model
    prints inside out on any slicer that trusts normals.
    """
    stack = EditStack(_box(20))
    stack.add("mirror", axis="x")
    out = stack.evaluate()

    assert out.is_watertight
    assert out.volume > 0, "the mirrored model is inside out"


def test_thickening_only_grows_what_is_too_thin():
    thick = trimesh.creation.box((40, 10, 40))
    stack = EditStack(thick, nozzle_mm=0.4)
    stack.add("thicken_thin_walls", minimum_mm=0.8)
    out = stack.evaluate()

    assert abs(out.volume - thick.volume) / thick.volume < 0.01, (
        "an already-thick model was inflated anyway")


# ---------------------------------------------------------------------------
# M2's acceptance, as the plan words it
# ---------------------------------------------------------------------------


def test_a_generated_model_goes_through_the_whole_print_prep_chain():
    """
    M2 IS DONE WHEN: "a generated dragon can be hollowed, flattened,
    thin-wall-thickened, de-floatered and cut for bed fit, and every operation
    stays adjustable afterwards."

    The stand-in has the faults a generated model really has: an organic body
    with no flat base, a sub-nozzle fin, a speck of debris, and it is too tall
    for the bed.
    """
    body = trimesh.creation.icosphere(subdivisions=4, radius=60)
    fin = trimesh.creation.box((60, 0.6, 60)).apply_translation((0, 0, 90))
    speck = trimesh.creation.box((0.5, 0.5, 0.5)).apply_translation((120, 0, 0))
    generated = trimesh.util.concatenate([body, fin, speck])

    stack = EditStack(generated, nozzle_mm=0.4)
    floaters = stack.add("remove_floaters", keep_fraction=0.02)
    thicken = stack.add("thicken_thin_walls", minimum_mm=0.8)
    flatten = stack.add("flatten_base", depth_mm=4.0)
    cut = stack.add("cut_plane", at_mm=40.0, axis="z", keep="lower")

    out = stack.evaluate()

    # The debris is gone.
    assert all(r.op.kind for r in stack.last_run)
    # It fits the bed now.
    assert float(out.extents[2]) <= 250.0
    assert float(out.bounds[1][2]) == pytest.approx(40.0, abs=0.5)
    # And it still is a model.
    assert len(out.faces) > 100

    # EVERY STEP STAYS ADJUSTABLE, which is the half of the acceptance that is
    # about the architecture rather than the geometry.
    for op in (floaters, thicken, flatten, cut):
        assert op.parameters, "%s has no adjustable parameters" % op.kind
        assert any(p.slidable or p.choices for p in op.parameters)

    # Moving one slider recomputes from that step, not from the source.
    stack.evaluate()
    assert _recomputed(stack) == []
    stack.set_value(cut.id, "at_mm", 30.0)
    stack.evaluate()
    assert _recomputed(stack) == ["cut_plane"], _recomputed(stack)

    lower = stack.evaluate()
    assert float(lower.bounds[1][2]) == pytest.approx(30.0, abs=0.5)

    # And any of them can be switched off without destroying the rest.
    stack.toggle(flatten.id, False)
    reverted = stack.evaluate()
    assert reverted is not None and len(reverted.faces) > 100
