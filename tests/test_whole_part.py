"""
whittle does not half-build anything.

Either a part is there and works, or the run failed and said why. There is
no third state worth having, and the third state is the one that costs
somebody an afternoon: a directory that looks like a part, holds the name,
cannot be rebuilt, and has nothing in it to read.

IT WAS REACHABLE, not theoretical. The export wrote the mesh to its final
home and the rest of the bundle afterwards - spec, report, regression,
renders. Anything failing in between left `out/thing.stl` and nothing else.
Proven by making write_bundle raise, which is what these tests do.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from whittle import api
from whittle.agent import bundle as bundle_mod

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "parts" / "a_hinge" / "spec.yaml"


@pytest.fixture
def workshop(tmp_path, monkeypatch):
    """A parts directory of its own, so nothing here touches the library."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "parts").mkdir()
    spec = tmp_path / "spec.yaml"
    spec.write_text(SPEC.read_text())
    return spec


def _left(tmp_path) -> list[str]:
    return sorted(p.relative_to(tmp_path).as_posix()
                  for p in (tmp_path / "parts").rglob("*"))


def test_a_build_that_fails_leaves_nothing_behind(workshop, tmp_path):
    """
    THE WHOLE POINT. A failure carries its reason in the exception, which
    the caller turns into a sentence; a directory of fragments adds nothing
    to that and outlives it.
    """
    with mock.patch.object(bundle_mod, "write_bundle",
                           side_effect=RuntimeError("disk full")):
        with pytest.raises(Exception):
            api.build(spec_path=workshop, out_dir=tmp_path / "parts" / "hinge",
                      bundle=True)

    assert _left(tmp_path) == [], (
        "a failed build left %s" % ", ".join(_left(tmp_path))
    )


def test_a_build_that_works_lands_exactly_where_it_was_told(workshop, tmp_path):
    """
    The other half: an explicit out_dir is honoured to the letter, because
    `whittle build parts/vent/spec.yaml --out parts/vent` rebuilding in
    place is the whole point of a spec being the durable artifact.
    """
    part = api.build(spec_path=workshop, out_dir=tmp_path / "parts" / "hinge",
                     bundle=True, render=False)

    home = tmp_path / "parts" / "hinge"
    assert (home / "spec.yaml").is_file()
    assert (home / "report.md").is_file()
    assert (home / "regression.json").is_file()

    # AND EVERY PATH IT REPORTS IS THE REAL ONE, not the scratch name it was
    # assembled under - the run record, the clients and the report all take
    # these and would otherwise name a directory that no longer exists.
    assert Path(part.stl).is_file()
    assert home in Path(part.stl).parents
    for path in (part.files.values() if isinstance(part.files, dict) else part.files):
        assert Path(path).is_file(), "%s does not exist" % path
        assert home in Path(path).parents


def test_a_failed_rebuild_leaves_the_part_that_was_already_there(workshop, tmp_path):
    """
    A REBUILD IN PLACE IS THE ORDINARY CASE, and the dangerous one: the part
    being replaced is real, somebody has printed it, and a failure halfway
    through must not take it with it. The old one is moved aside and only
    removed once the new one has landed.
    """
    home = tmp_path / "parts" / "hinge"
    api.build(spec_path=workshop, out_dir=home, bundle=True, render=False)
    before = (home / "spec.yaml").read_text()

    with mock.patch.object(bundle_mod, "write_bundle",
                           side_effect=RuntimeError("boom")):
        with pytest.raises(Exception):
            api.build(spec_path=workshop, out_dir=home, bundle=True)

    assert (home / "spec.yaml").is_file(), "a failed rebuild destroyed the part"
    assert (home / "spec.yaml").read_text() == before
    assert (home / "report.md").is_file()


def test_nothing_that_looks_like_a_part_is_left_lying_around(workshop, tmp_path):
    """
    A scratch directory is swept on the way out, and is named so that even
    one surviving a power cut is not mistaken for a part: library.read_entry
    needs a spec, a draft or an import record, and a half-written directory
    has none of the three until the moment it is finished.
    """
    api.build(spec_path=workshop, out_dir=tmp_path / "parts" / "hinge",
              bundle=True, render=False)

    strays = [p.name for p in (tmp_path / "parts").iterdir()
              if p.name.startswith(".")]
    assert not strays, "left %s behind" % ", ".join(strays)

    from whittle import library

    library.forget()
    seen = library.scan([tmp_path / "parts"])
    assert [e.name for e in seen] == ["hinge"], [e.name for e in seen]
