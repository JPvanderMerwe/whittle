"""
The GLB fixtures the React Native client is tested against are not stale.

The client parses GLB itself - app/src/glb.ts says why - and it is proved
against files in app/tests/fixtures that came out of the engine's own export
path. Those files are committed so `npm test` needs no Python, which means
they can silently fall behind the exporter.

So this is the same arrangement design/tokens.json has with tests/test_tokens.py:
the generator is re-run in memory and the result compared. An export path that
changed without the fixtures being regenerated is a test failure here rather
than a viewport that draws the wrong thing on a phone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "app" / "tests" / "fixtures"
MANIFEST = FIXTURES / "manifest.json"


def _manifest() -> dict:
    if not MANIFEST.is_file():
        pytest.fail("no fixture manifest at %s - run: python tools/glb_fixtures.py"
                    % MANIFEST.relative_to(ROOT))
    return json.loads(MANIFEST.read_text())


def test_every_case_has_its_file():
    for case in _manifest()["cases"]:
        path = FIXTURES / case["file"]
        assert path.is_file(), "%s is named in the manifest and missing" % case["file"]
        assert path.stat().st_size == case["bytes"], (
            "%s is %d bytes and the manifest says %d - run: "
            "python tools/glb_fixtures.py"
            % (case["file"], path.stat().st_size, case["bytes"]))


def test_the_fixtures_still_match_what_the_exporter_writes():
    """
    Re-export each case and compare the bytes.

    Byte equality rather than a tolerance, deliberately. These are the same
    shapes built the same way through the same function; if the bytes moved,
    something in the export path moved, and the client's reader has been
    proved against a file the server no longer sends.
    """
    from whittle.web.projects import to_glb

    from tools.glb_fixtures import _cases

    expected = {case["name"]: case for case in _manifest()["cases"]}
    assert set(expected) == {name for name, _ in _cases()}, (
        "the manifest and tools/glb_fixtures.py disagree about which cases "
        "exist - run: python tools/glb_fixtures.py")

    for name, mesh in _cases():
        fresh = to_glb(mesh)
        stored = (FIXTURES / expected[name]["file"]).read_bytes()
        assert fresh == stored, (
            "%s.glb no longer matches what the exporter writes - run: "
            "python tools/glb_fixtures.py" % name)


def test_the_expectations_come_from_the_mesh_and_not_from_the_glb():
    """
    The measurements in the manifest are trimesh's, re-measured here.

    This is what makes the client's test worth running: the numbers it asserts
    against describe the MESH, so a reader that agrees with them is reading
    the geometry rather than agreeing with the exporter about itself.
    """
    import numpy as np

    from tools.glb_fixtures import _cases

    expected = {case["name"]: case for case in _manifest()["cases"]}

    for name, mesh in _cases():
        case = expected[name]
        assert int(len(mesh.faces)) == case["triangles"]
        assert int(len(mesh.vertices)) == case["vertices"]
        assert float(mesh.area) == pytest.approx(case["area_mm2"], rel=1e-9)
        bounds = np.asarray(mesh.bounds, dtype=float)
        for axis in range(3):
            assert float(bounds[0][axis]) == pytest.approx(case["min"][axis], abs=1e-6)
            assert float(bounds[1][axis]) == pytest.approx(case["max"][axis], abs=1e-6)
