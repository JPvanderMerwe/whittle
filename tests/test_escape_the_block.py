"""
A part built from primitives escaping to the template that now claims it.

THE FAILURE, IN THE OWNER'S WORDS
---------------------------------
"i tried to reprompt the phone stand in the app as this phone stand looks
nothing like the production stls that are available for download online...
whittle has created an ugly block for the phone stand"

He was right, and the cause was one line in agent/refine.py:

    if spec.level == 2 or not spec.template:
        return refine_ops(...)

parts/phone_stand is a 100 x 100 x 30 rounded prism with a wedge cut out of it
and a pocket in the top - a block with a slit in it - because it was built
BEFORE there was a stand template. refine_ops nudges the numbers of the
primitives a part already has, so reprompting it asked a model to make a
better block. It could never become a stand, however many times anybody asked.

That breaks the promise the product rests on. "Work it until it is right" is
worth nothing if an object cannot escape the way it was first built.

WHAT MUST NOT HAPPEN EITHER
---------------------------
A part that is deliberately made of primitives, and that no template claims,
must be left alone - switching it would throw away somebody's work. And
nothing is ever destroyed regardless: a refine writes a NEW part and leaves
the old one on disk, which is what makes this safe at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whittle import api
from whittle.agent.refine import _rebuild_as_template, _template_now_claims

ROOT = Path(__file__).resolve().parents[1]


def _spec(**over):
    raw = {
        "name": "phone_stand", "level": 2, "material": "petg",
        "nozzle_mm": 0.4, "layer_mm": 0.2,
        "ops": [{"op": "rounded_prism", "width_mm": 100, "depth_mm": 100,
                 "height_mm": 30, "corner_r_mm": 5}],
    }
    raw.update(over)
    return api.validate_spec(raw)


# ---------------------------------------------------------------------------
# it notices
# ---------------------------------------------------------------------------

def test_a_block_called_a_phone_stand_is_claimed_by_the_stand_template():
    """THE EXACT PART THE OWNER WAS LOOKING AT, by name."""
    assert _template_now_claims(_spec(), "make it look like a proper stand") == "stand"


def test_the_parts_own_name_is_enough_on_its_own():
    """
    The instruction usually carries only the CHANGE - "make it look better" -
    and claims nothing. The name carries what the thing is, and it is what the
    person called it.
    """
    assert _template_now_claims(_spec(), "make it nicer") == "stand"


def test_a_part_that_already_has_a_template_is_left_alone():
    """There is nothing to escape from; this path must not fire at all."""
    assert _template_now_claims(
        _spec(name="birdhouse", level=1, template="enclosure", ops=[], params={}),
        "make the roof triangular") is None


def test_a_block_no_template_claims_is_left_as_primitives():
    """
    Rule 31: composing is the product, not the fallback. A part nothing claims
    keeps its operations - switching it would be throwing work away, and there
    is nothing to switch it to.
    """
    assert _template_now_claims(_spec(name="widget_7"), "make it wider") is None


# ---------------------------------------------------------------------------
# it rebuilds, with no model
# ---------------------------------------------------------------------------

def test_the_block_comes_back_as_a_stand():
    result = _rebuild_as_template(_spec(), "stand", "make it look like a stand")
    assert result is not None and result.ok
    assert result.spec.template == "stand"
    assert result.spec.level == 1
    # THE OPERATIONS ARE GONE. A spec carrying both is two descriptions of one
    # part, and the builder would have to choose between them.
    assert not getattr(result.spec, "ops", None)


def test_it_says_what_it_did_and_why():
    """
    Rule 32: an object changing what it is MADE OF is the largest thing that
    can happen to it, and it must not happen silently.
    """
    note = _rebuild_as_template(_spec(), "stand", "make it nicer").note
    assert "stand" in note
    assert "primitives" in note
    # And that the old one is still there, because that is what makes it safe.
    assert "still in the library" in note


def test_no_model_is_involved():
    """
    RULE 11: the system stays fully usable with zero model, and a part escaping
    a bad first build is exactly the case where nobody should wait for a GPU.
    `_rebuild_as_template` takes no profile and no backend - if it ever needs
    one, this call raises rather than quietly reaching for the network.
    """
    import inspect

    taken = inspect.signature(_rebuild_as_template).parameters
    assert "profile" not in taken and "backend" not in taken


def test_what_was_said_is_read_against_the_new_template():
    """
    The instruction is about the thing it is becoming, so it is read against
    THAT schema - not dropped because the old spec had no such field.
    """
    result = _rebuild_as_template(_spec(), "stand", "make it lean back more, 78 degrees")
    assert result is not None
    assert result.spec.params.get("lean_deg") == pytest.approx(78.0)


def test_an_instruction_that_reaches_nothing_is_said_out_loud():
    result = _rebuild_as_template(_spec(), "stand", "make it look nicer somehow")
    assert result is not None
    assert "Nothing geometric in" in result.note


def test_the_rebuilt_part_actually_builds_and_verifies(tmp_path):
    """
    A SPEC THAT DOES NOT BUILD IS WORSE THAN THE BLOCK IT REPLACED. The block
    at least existed.
    """
    result = _rebuild_as_template(_spec(), "stand", "make it a stand")
    api.write_spec(result.spec, tmp_path / "spec.yaml")
    api.build(tmp_path / "spec.yaml", out_dir=tmp_path)
    assert next(tmp_path.rglob("*.stl"), None) is not None


def test_the_real_part_on_disk_is_the_one_this_was_written_for():
    """
    Not a fixture: the actual file the owner was looking at. If somebody
    rebuilds parts/phone_stand from the template one day this test becomes
    pointless rather than wrong, and skipping is the honest answer.
    """
    spec_path = ROOT / "parts" / "phone_stand" / "spec.yaml"
    if not spec_path.is_file():
        pytest.skip("parts/phone_stand is not on this machine")
    loaded = api.load_spec(spec_path)
    spec = loaded[0] if isinstance(loaded, tuple) else loaded
    if spec.template:
        pytest.skip("parts/phone_stand has already been rebuilt as a template")
    assert _template_now_claims(spec, "make it look like a real phone stand") == "stand"
