"""
The third way in: a sentence to a mesh, for what no template covers.

WHAT IS WORTH TESTING WHILE THE BACKEND IS null. Not the geometry - there is
none. The CONTRACT: that whittle still installs and runs with nothing
configured, that the refusal is useful rather than a shrug, and that a
generated mesh could never claim dimensions nobody measured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whittle.imagine import BACKENDS, ImagineError, ImagineUnavailable, make_imaginer
from whittle.imagine.base import Imagined, Imaginer


def test_whittle_runs_with_no_text_to_mesh_backend():
    """
    Rule 10: whittle installs and runs with no weights, no torch and no
    network. The default is null and it is a configuration rather than a
    placeholder.
    """
    from whittle import api

    imaginer = make_imaginer(api.config())
    assert imaginer.name == "null"
    assert isinstance(imaginer, Imaginer)


def test_the_refusal_says_what_is_missing_and_what_it_would_cost(tmp_path):
    """
    A MISSING FEATURE THAT SAYS ONLY "not available" IS A DEAD END, and this
    one has a real trade-off behind it: a generated mesh has no dimensions
    anybody chose. Somebody deciding should be told that, not just told no.
    """
    with pytest.raises(ImagineUnavailable) as caught:
        make_imaginer().imagine("a gargoyle", tmp_path)

    said = str(caught.value)
    assert "a gargoyle" in said, "the refusal does not name what was asked for"
    assert "GPU" in said
    assert "template" in said
    assert "dimensions" in said


def test_an_unknown_backend_is_refused_by_name():
    """
    Never a silent fallback to null: a typo that quietly disables a feature
    is worse than an error. The same rule make_reconstructor follows.
    """
    with pytest.raises(ImagineError) as caught:
        make_imaginer(backend="hunyuan3dd")
    assert "hunyuan3dd" in str(caught.value)
    assert "null" in str(caught.value)


def test_a_generated_mesh_has_no_millimetres_until_something_measures_one():
    """
    THE RULE THAT KEEPS THIS HONEST. There is no camera, no reference object
    and no scale in a sentence, so a generated mesh is dimensionless. The
    same rule a reconstruction from a photo follows, and the reason rules 9
    and 13 are not quietly suspended for neural output.
    """
    out = Imagined(mesh_path=Path("x.stl"), prompt="a gargoyle", backend="null",
                   extent=(1.0, 2.0, 0.5))
    assert out.has_scale is False
    assert out.extent_mm() is None
    assert out.printable is False, "nothing is printable until verify has run"

    out.scale_mm_per_unit = 40.0
    out.scale_source = "the person said it is 40 mm across"
    assert out.extent_mm() == (40.0, 80.0, 20.0)


def test_only_backends_that_can_be_run_are_listed():
    """
    Wiring a backend from its README without ever calling it is guessing at
    an interface - rule 9 - and a text-to-3D API guessed at fails after
    somebody has waited on a GPU. BACKENDS lists what this can actually
    drive.
    """
    assert BACKENDS == ("null",), (
        "a backend was added to the list; it needs an installation this was "
        "run against, not a README"
    )
