"""
Opening a part Whittle built as an edit session.

THE TWO HALVES MEETING IS THE POINT. Whittle has two ways in - describe a part
and it gets built, or bring a mesh and get sliders - and until open_part existed
they were separate products sharing a process: you could describe a bracket,
watch it build, look at it, and have nothing to turn.

So these do not check for a 200. They check that what comes back is a real edit
session: the nine operations apply to it, a slider moves its geometry, and the
gate has an opinion about the result. A route that returns a payload nobody can
edit would pass a status check and fail the product.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import trimesh

from whittle.web import projects as P

BED = (220.0, 220.0, 250.0)


@pytest.fixture
def built_part(tmp_path: Path) -> Path:
    """
    A stand-in for parts/<name>/out/<name>.stl.

    Written rather than taken from parts/ on purpose: the test must not depend
    on which parts happen to be on this machine, and must not be able to touch
    one. A build on disk is the record of a verified build.
    """
    mesh = trimesh.creation.box((60.0, 40.0, 20.0))
    path = tmp_path / "bracket.stl"
    path.write_bytes(mesh.export(file_type="stl"))
    return path


def test_a_built_part_opens_as_an_editable_session(built_part: Path):
    project = P.open_part(built_part, nozzle_mm=0.4, bed_mm=BED)
    try:
        payload = project.payload()
        assert payload["format"] == "STL"
        assert payload["size_mm"] == [60.0, 40.0, 20.0]
        # NO STACK YET, AND THAT IS RIGHT. The part arrives as it was built;
        # the operations are what the person does next.
        assert payload["edits"] == []
        assert "printable" in payload["report"]
    finally:
        P.PROJECTS.close(project.id)


def test_the_units_are_not_guessed_at_for_a_part_we_built(built_part: Path):
    """
    An STL carries no units and the importer has to guess - it reads 60 across
    and says "that is an ordinary size for something printed". For a part THIS
    machine built there is nothing to guess: the engine works in millimetres
    and wrote the file. Guessing at our own output would be inventing doubt.
    """
    project = P.open_part(built_part, nozzle_mm=0.4, bed_mm=BED)
    try:
        units = project.payload()["units"]
        assert units["units"] == "mm"
        assert units["assumed"] is False
    finally:
        P.PROJECTS.close(project.id)


def test_every_operation_applies_to_it(built_part: Path):
    """
    Not "the route works" - the nine operations work on what it returns. A
    session you cannot hollow is not an edit session.

    EACH ON ITS OWN SESSION, which is not a convenience. Stacking all nine on
    one model refuses at `hollow`, and correctly: `cut_plane` ran first and
    left an open surface, so there is no inside to take out. That is the gate
    doing its job rather than a fault, and testing them as one chain would
    have measured whether nine arbitrary operations happen to compose - which
    nobody asked them to.
    """
    from whittle.edit import REGISTRY

    for kind in sorted(REGISTRY):
        project = P.open_part(built_part, nozzle_mm=0.4, bed_mm=BED)
        try:
            P.add_edit(project, kind, {})
            assert [op["kind"] for op in project.payload()["edits"]] == [kind]
            assert len(project.evaluate().faces) > 0, (
                "%s left nothing to draw" % kind)
        finally:
            P.PROJECTS.close(project.id)


def test_a_slider_moves_the_geometry_of_a_built_part(built_part: Path):
    """
    The whole promise in one assertion: a number the person drags changes the
    mesh that comes out.
    """
    project = P.open_part(built_part, nozzle_mm=0.4, bed_mm=BED)
    try:
        # BEFORE THE OPERATION IS ADDED. Adding one applies its own default
        # immediately - that is the point of a parameterised stack - so
        # measuring after the add measures the default, not the original.
        before = float(project.evaluate().extents[2])

        added = P.add_edit(project, "scale_to_height", {})["added"]
        P.set_value(project, added, "height_mm", 50.0, final=True)
        after = float(project.evaluate().extents[2])

        assert before == pytest.approx(20.0, abs=0.01)
        assert after == pytest.approx(50.0, abs=0.01)
    finally:
        P.PROJECTS.close(project.id)


def test_the_part_on_disk_is_not_touched(built_part: Path):
    """
    RULE: a part in parts/ is the record of a verified build. An edit session
    works on a copy; it does not quietly rewrite the thing that was verified.
    """
    before = built_part.read_bytes()

    project = P.open_part(built_part, nozzle_mm=0.4, bed_mm=BED)
    try:
        added = P.add_edit(project, "scale_uniform", {})["added"]
        P.set_value(project, added, "factor", 2.0, final=True)
        assert float(project.evaluate().extents[2]) == pytest.approx(40.0, abs=0.01)
    finally:
        P.PROJECTS.close(project.id)

    assert built_part.read_bytes() == before


def test_a_part_with_no_mesh_says_so_rather_than_failing_oddly(tmp_path: Path):
    missing = tmp_path / "never-built.stl"
    with pytest.raises(FileNotFoundError, match="no mesh on disk"):
        P.open_part(missing, nozzle_mm=0.4, bed_mm=BED)
