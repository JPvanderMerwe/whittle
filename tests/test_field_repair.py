"""
A field an op does not have, dropped rather than asked about.

THE RUN THIS COMES FROM. Asked for "Redbull can" the model finally wrote a
correct `revolve` - the right operation, reached for because of the
vocabulary steer, with a real profile - and hung a `height_mm` on it, which
revolve does not have because the height is in the profile points. The whole
spec was rejected over a field that said nothing the op had not already been
told, and the next attempt came back with a worse answer.
"""

from __future__ import annotations

import pytest

from whittle.agent.loop import SpecRejected, _drop_unknown_fields, validate_dsl_reply

DEFAULTS = {"material": "petg", "nozzle_mm": 0.4, "layer_mm": 0.2}


def test_an_unknown_field_goes_when_that_makes_the_op_valid():
    op = {"op": "revolve",
          "points": [[0, 0], [33, 0], [33, 115], [0, 115]],
          "height_mm": 66}
    assert _drop_unknown_fields(op) == ["height_mm"]
    assert "height_mm" not in op
    assert op["points"], "the repair took the profile with it"


def test_an_op_that_is_still_broken_is_still_rejected():
    """
    NARROW ON PURPOSE. A missing REQUIRED field is the model failing to say
    something, and guessing what it meant is what rule 9 forbids. The extra
    fields go back, so the rejection describes what the model actually wrote
    rather than a half-stripped version of it.
    """
    op = {"op": "rounded_prism", "depth_mm": 20, "nonsense": 1}
    assert _drop_unknown_fields(op) == []
    assert op["nonsense"] == 1, "the op was left half-stripped after failing"


def test_an_old_field_spelling_is_not_dropped():
    """
    `cone` takes `bottom_d_mm` as well as `bottom_diameter_mm`. Dropping the
    old spelling would break every spec on disk written with it, and rule 11
    is that a stored spec always rebuilds.
    """
    op = {"op": "cone", "bottom_d_mm": 20, "top_d_mm": 5, "height_mm": 30}
    assert _drop_unknown_fields(op) == []
    assert op["bottom_d_mm"] == 20


def test_a_spec_with_one_stray_field_is_accepted_and_says_so():
    """
    The end-to-end shape of it: the spec validates, and what was ignored is
    written down. whittle does not change what somebody's model said without
    showing it.
    """
    spec = validate_dsl_reply({
        "name": "drink_can",
        "ops": [{"op": "revolve",
                 "points": [[0, 0], [33, 0], [33, 115], [0, 115]],
                 "height_mm": 115}],
        "print_axis": "z",
    }, DEFAULTS)

    assert spec.ops[0]["op"] == "revolve"
    assert "height_mm" not in spec.ops[0]

    # AND IT SAYS WHAT IT IGNORED. whittle does not change what a model
    # wrote without showing it - recorded on the run rather than on the
    # spec, because the spec says what the part IS.
    said = getattr(spec, "_repairs", [])
    assert said and "height_mm" in said[0], said

    # AND IT BUILDS, which is the only reason any of this is worth doing.
    from whittle.spec.dsl import run_ops

    scene = run_ops(spec.ops, print_axis="z")
    assert scene.solid.val().Volume() > 0


def test_a_spec_that_is_wrong_in_a_way_this_cannot_fix_is_still_refused():
    with pytest.raises(SpecRejected) as caught:
        validate_dsl_reply({
            "name": "broken",
            "ops": [{"op": "rounded_prism", "depth_mm": 20}],
        }, DEFAULTS)
    assert "width_mm" in str(caught.value)
