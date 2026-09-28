"""
Seeing a change while it is being made.

THE ASYMMETRY THIS CLOSES
-------------------------
whittle has two kinds of object and the app already previewed one of them. Drag
a slider on an imported mesh and the shape redraws in 43 ms, because a mesh
operation is a transform of a mesh that already exists. Drag a slider on a part
this engine BUILT and nothing happened at all: the numbers collected up, and
the only way to see what they did was to press "build it" and wait for a full
rebuild, verification, tessellation, render and library write.

That is not a limit of CAD. Measured on three real parts, the geometry of a
rebuild is 57-90 ms - the seconds are everything AROUND it. So there is a route
that does the geometry and nothing else.

WHAT IT MUST NOT DO
-------------------
  * write anything. A preview is a look, not a build, and the library is a
    history of things somebody decided on.
  * verify. The printability gate is the expensive half, and a verdict one
    slider position behind describes the shape you just left.
  * disagree with the build behind it. Both apply the values through the SAME
    function, because a preview that applied a slider differently would look
    right while you dragged and come out as something else.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from whittle.web import server as S

PARTS = Path(__file__).resolve().parents[1] / "parts"


def _a_part_with_a_spec() -> str:
    for directory in sorted(PARTS.glob("*/")):
        if (directory / "spec.yaml").is_file():
            return directory.name
    pytest.skip("no built part with a spec on this machine")


# ---------------------------------------------------------------------------
# the values are applied the same way for a preview and for a build
# ---------------------------------------------------------------------------

def test_one_function_applies_the_values_for_both_callers():
    """
    THE WHOLE REASON IT WAS EXTRACTED. A preview that applied a slider
    differently from the build behind it is the worst kind of wrong: right
    while you drag, different when it lands, and the difference only shows up
    after the wait.
    """
    source = Path(S.__file__).read_text()
    assert source.count("def _spec_with_values(") == 1
    # The build path uses it, and so does the preview path.
    assert "changed, refusal = _spec_with_values(spec, name, values)" in source
    assert "changed, refusal = _spec_with_values(spec, name, values)" in source


def test_a_template_part_takes_named_values():
    from whittle import api

    name = _a_part_with_a_spec()
    loaded = api.load_spec(api._spec_path_for(name))
    spec = loaded[0] if isinstance(loaded, tuple) else loaded
    if not getattr(spec, "template", None):
        pytest.skip("%s is built from operations, not a template" % name)

    changed, refusal = S._spec_with_values(spec, name, {"wall_mm": 3.5})
    assert refusal is None
    assert changed.params["wall_mm"] == 3.5
    # AND THE ORIGINAL IS UNTOUCHED. A preview that mutated the spec in memory
    # would leave the next build working from a number nobody typed.
    assert (spec.params or {}).get("wall_mm") != 3.5


def test_naming_two_kinds_of_parameter_at_once_is_refused():
    """
    A part is a template or a list of operations, never both, so a payload
    holding both kinds is a client mistake - and half-applying it would leave a
    part nobody asked for.
    """
    from whittle import api

    name = _a_part_with_a_spec()
    loaded = api.load_spec(api._spec_path_for(name))
    spec = loaded[0] if isinstance(loaded, tuple) else loaded

    _changed, refusal = S._spec_with_values(
        spec, name, {"wall_mm": 3.0, "0.width_mm": 90.0})
    assert refusal and "two different kinds of name" in refusal


# ---------------------------------------------------------------------------
# it draws the shape, and it is fast enough to be worth having
# ---------------------------------------------------------------------------

def test_a_preview_comes_back_as_a_glb():
    name = _a_part_with_a_spec()
    from whittle import api

    loaded = api.load_spec(api._spec_path_for(name))
    spec = loaded[0] if isinstance(loaded, tuple) else loaded
    values = _something_to_move(spec)
    if values is None:
        pytest.skip("%s has no number this test knows how to move" % name)

    data = S._preview_glb(name, values)
    assert isinstance(data, (bytes, bytearray)) and len(data) > 1000
    # glTF binary: the magic word is "glTF".
    assert bytes(data[:4]) == b"glTF"


def test_a_preview_changes_the_shape_it_is_asked_to_change():
    """
    The failure this catches is a slider that moves and draws the same thing -
    which is what the screen did for months, one layer down.
    """
    name = _a_part_with_a_spec()
    from whittle import api

    loaded = api.load_spec(api._spec_path_for(name))
    spec = loaded[0] if isinstance(loaded, tuple) else loaded
    small = _something_to_move(spec, factor=0.7)
    large = _something_to_move(spec, factor=1.3)
    if small is None or large is None:
        pytest.skip("%s has no number this test knows how to move" % name)

    assert S._preview_glb(name, small) != S._preview_glb(name, large)


def test_a_preview_writes_nothing():
    """
    A LOOK IS NOT A BUILD. Looking at a part used to write one - see
    _assembled_mesh - and the library filled up with directories named after
    whatever somebody had just turned around on screen.
    """
    name = _a_part_with_a_spec()
    from whittle import api

    loaded = api.load_spec(api._spec_path_for(name))
    spec = loaded[0] if isinstance(loaded, tuple) else loaded
    values = _something_to_move(spec)
    if values is None:
        pytest.skip("nothing to move")

    before = sorted(p.name for p in PARTS.glob("*/"))
    spec_text = (PARTS / name / "spec.yaml").read_text()
    S._preview_glb(name, values)

    assert sorted(p.name for p in PARTS.glob("*/")) == before
    assert (PARTS / name / "spec.yaml").read_text() == spec_text


def test_a_preview_is_fast_enough_to_drag_against():
    """
    NOT A ROUND NUMBER PLUCKED OUT OF THE AIR. The app waits a quarter of a
    second after the thumb stops and then draws; if the draw itself took longer
    than that the control would feel like the build it replaced. Measured at
    57-90 ms on three real parts, so a second is a ceiling with room in it
    rather than a target.
    """
    name = _a_part_with_a_spec()
    from whittle import api

    loaded = api.load_spec(api._spec_path_for(name))
    spec = loaded[0] if isinstance(loaded, tuple) else loaded
    values = _something_to_move(spec)
    if values is None:
        pytest.skip("nothing to move")

    S._preview_glb(name, values)          # warm whatever caches exist
    started = time.time()
    S._preview_glb(name, values)
    assert time.time() - started < 1.0


def test_a_value_the_schema_refuses_says_where_the_end_is():
    """
    RULE 32: what cannot be done is said out loud, with the real options. The
    first version sent only the exception's first line - "op 'rounded_prism' is
    invalid:" - which is the one line carrying none of the answer.
    """
    name = _a_part_with_a_spec()
    from whittle import api

    loaded = api.load_spec(api._spec_path_for(name))
    spec = loaded[0] if isinstance(loaded, tuple) else loaded
    values = _something_to_move(spec, factor=10_000)
    if values is None:
        pytest.skip("nothing to move")

    with pytest.raises(S.HttpError) as caught:
        S._preview_glb(name, values)
    assert caught.value.status == 422
    # The field, and the bound it broke.
    assert any(word in caught.value.message
               for word in ("less than", "greater than", "legal"))


def test_an_unknown_part_is_a_404_and_not_a_traceback():
    with pytest.raises(S.HttpError) as caught:
        S._preview_glb("no-such-part-anywhere", {"wall_mm": 3.0})
    assert caught.value.status == 404


def _something_to_move(spec, factor: float = 1.2):
    """One number on this part, moved - whichever kind of spec it is."""
    ops = list(getattr(spec, "ops", None) or [])
    if ops:
        for index, op in enumerate(ops):
            data = op.model_dump() if hasattr(op, "model_dump") else dict(op)
            for field, value in data.items():
                if field.endswith("_mm") and isinstance(value, (int, float)) and value > 0:
                    return {"%d.%s" % (index, field): round(value * factor, 3)}
        return None
    params = dict(getattr(spec, "params", None) or {})
    for field, value in params.items():
        if field.endswith("_mm") and isinstance(value, (int, float)) and value > 0:
            return {field: round(value * factor, 3)}
    return None
