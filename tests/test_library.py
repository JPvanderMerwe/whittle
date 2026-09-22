"""
The local library.

A downloaded STL is a frozen mesh: you cannot make it 20 mm wider, cannot
change it for a different printer, cannot ask it anything. Every part here is a
SPEC, so it rebuilds exactly, at whatever size, in whatever material. That is
why this indexes spec.yaml rather than *.stl, and why sharing sends a spec.

Nothing here opens a socket.
"""

from pathlib import Path

import pytest

from whittle import api, library

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def entries():
    """
    BOTH ROOTS, because the library is both.

    This scanned only parts/, which is exactly the blind spot the import tests
    below exist to cover - so with the old fixture they skipped, silently, and
    would have gone on skipping after a regression put imports back in the
    dark. Absolute paths rather than library.DEFAULT_ROOTS: those are relative
    and would make the fixture depend on where pytest was started.
    """
    from whittle import imports

    return library.scan([ROOT / "parts", ROOT / imports.IMPORT_ROOT])


def test_the_library_finds_the_parts(entries):
    names = {e.name for e in entries}
    assert {"vent_louvre", "loop_keyring"} <= names


def test_an_entry_knows_its_template_without_building(entries):
    """
    WITHOUT BUILDING is the whole point, so this must not require a build.
    It used to assert `vent.built`, which contradicted its own name and failed
    in a fresh clone - parts/*/out/ is gitignored on purpose, because the
    meshes rebuild from the spec in seconds and would otherwise churn the
    history on every build.
    """
    vent = next(e for e in entries if e.name == "vent_louvre")
    assert vent.template == "louvre_vent"
    assert vent.material == "petg"


def test_the_envelope_comes_from_the_stored_baseline(entries):
    """
    Read from regression.json rather than by loading every mesh - a library
    that measures its whole contents to draw a list is a library that takes a
    second to open.
    """
    vent = next(e for e in entries if e.name == "vent_louvre")
    assert vent.envelope_mm is not None
    assert vent.volume_cm3 > 20


def test_search_matches_the_name(entries):
    """
    A word in a part's name finds it - and finds nothing it is not in.

    THIS ASSERTED AN EXACT LIST, `== ["loop_keyring"]`, against a directory
    people build into. It was true on the day it was written and it broke the
    first time somebody generated "a keyring tag 40 mm long and 3 mm thick",
    which is the search working correctly: that part is a keyring and should be
    found. An exact list here reports using the program as a regression.

    The rule underneath is the same one test_search_matches_what_the_template
    _makes already checks properly: the known part is among the hits, and every
    hit earned its place. Both halves matter - dropping the second would pass
    an implementation that returned the whole library.
    """
    hits = library.search("keyring", entries)

    assert any(e.name == "loop_keyring" for e in hits), (
        "the part named loop_keyring did not answer to 'keyring'"
    )
    for e in hits:
        assert "keyring" in e.haystack(), (
            "%r matched 'keyring' but the word appears nowhere in it" % e.name
        )

    # And a word in nothing finds nothing, so a match is a match rather than
    # the search having given up and returned everything.
    assert library.search("zzzznotaword", entries) == []


def test_search_matches_what_the_template_makes(entries):
    """
    The point of the whole thing. "Container" appears nowhere in the birdhouse's
    spec - it comes from the enclosure template's own list of what people call
    it. Without that, a search only finds what you happened to name things.
    """
    hits = library.search("container", entries)
    assert hits, "a part built from the enclosure should answer to 'container'"
    assert any(e.template == "enclosure" for e in hits)

    # NOT "all". "container" is deliberately claimed by the rectangular
    # enclosure AND the round vessel, because it is not a shape word - a
    # container is as often square as round. Every hit must come from a
    # template that actually claims the word; more than one may.
    from whittle.spec import registry

    for e in hits:
        assert "container" in registry.get(e.template).makes, (
            "%r matched 'container' but its template %r does not claim it"
            % (e.name, e.template)
        )


def test_search_matches_the_material(entries):
    assert len(library.search("petg", entries)) >= 2


def test_every_word_has_to_match(entries):
    assert library.search("vent keyring", entries) == []


def test_an_empty_search_returns_everything(entries):
    assert len(library.search("   ", entries)) == len(entries)


def test_search_is_case_insensitive(entries):
    assert library.search("VENT", entries) == library.search("vent", entries)


def test_a_draft_is_listed_and_marked(tmp_path):
    """
    A handoff that still needs editing is part of the library - hiding it is
    how a failed run gets forgotten about.
    """
    d = tmp_path / "halfdone"
    d.mkdir()
    (d / "spec.draft.yaml").write_text("name: halfdone\nlevel: 1\n")
    entry = library.read_entry(d)
    assert entry is not None
    assert entry.is_draft
    assert entry.summary() == "needs editing"


def test_a_directory_that_is_not_a_part_is_skipped(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "readme.txt").write_text("hello")
    assert library.read_entry(tmp_path / "notes") is None


# -- sharing ----------------------------------------------------------------


def test_a_shared_spec_is_small_and_readable(tmp_path, entries):
    vent = next(e for e in entries if e.name == "vent_louvre")
    out = api.export_spec(vent, tmp_path)
    assert out.is_file()
    assert out.stat().st_size < 8000, "a spec is text, not a mesh"
    assert "template: louvre_vent" in out.read_text()


def test_a_shared_spec_rebuilds_identically(tmp_path, entries):
    """
    The argument for specs over meshes, tested rather than asserted: a
    1 kB text file reproduces the part exactly.
    """
    from whittle.verify.regression import signature_of

    vent = next(e for e in entries if e.name == "vent_louvre")
    shared = api.export_spec(vent, tmp_path / "outbox")
    brought_in = api.import_spec(shared, into=tmp_path / "library")
    rebuilt = api.build(spec_path=brought_in.spec_path, out_dir=tmp_path / "built")

    original = api.verify(ROOT / "reference" / "vent_louvre.stl")
    assert signature_of(rebuilt.report.mesh).digest() == signature_of(original.mesh).digest()


def test_sharing_a_draft_is_refused(tmp_path):
    d = tmp_path / "halfdone"
    d.mkdir()
    (d / "spec.draft.yaml").write_text("name: halfdone\n")
    entry = library.read_entry(d)
    with pytest.raises(api.ApiError) as exc:
        api.export_spec(entry, tmp_path / "out.yaml")
    assert "still needs editing" in str(exc.value)


def test_an_invalid_spec_is_refused_on_the_way_in(tmp_path):
    """
    Better a clear message here than a confusing one at build time.
    """
    bad = tmp_path / "bad.spec.yaml"
    bad.write_text("name: x\nlevel: 1\nmaterial: petg\nnozzle_mm: -5\nlayer_mm: 0.2\n")
    with pytest.raises(api.ApiError) as exc:
        api.import_spec(bad, into=tmp_path / "lib")
    assert "nozzle_mm" in str(exc.value)


def test_importing_twice_does_not_overwrite(tmp_path, entries):
    vent = next(e for e in entries if e.name == "vent_louvre")
    shared = api.export_spec(vent, tmp_path / "outbox")
    a = api.import_spec(shared, into=tmp_path / "lib")
    b = api.import_spec(shared, into=tmp_path / "lib")
    assert a.directory != b.directory


def test_a_spec_that_needs_a_file_takes_it_along(tmp_path):
    """
    The keyring's spec points at a traced logo. A shared spec that leaves it
    behind builds nothing at the other end.
    """
    keyring = next(e for e in library.scan([ROOT / "parts"]) if e.name == "loop_keyring")
    if "logo_json" not in keyring.params:
        pytest.skip("this keyring does not use a traced logo")
    out = api.export_spec(keyring, tmp_path / "outbox")
    assert (out.parent / keyring.params["logo_json"]).is_file()


def test_the_library_never_opens_a_socket(monkeypatch):
    """It reads directories. That is all it does."""
    import socket

    real = socket.socket

    class Blocked(real):
        def __init__(self, *a, **k):
            raise AssertionError("the library must not touch the network")

    monkeypatch.setattr(socket, "socket", Blocked)
    assert library.scan([ROOT / "parts"])
    assert library.search("container", roots=[ROOT / "parts"]) is not None


# ---------------------------------------------------------------------------
# the two roots
# ---------------------------------------------------------------------------


def test_an_imported_mesh_is_in_the_library_at_all(entries):
    """
    THE BUG THIS PINS: an imported STL was editable for exactly as long as the
    session that imported it stayed open, and then it was gone.

    It failed twice over. Everything the engine builds lands in parts/ and
    everything a person brings in lands in library/, and only parts/ was
    scanned - and even with both scanned, `read_entry` returned None for any
    directory without a spec, which is every import. So a mesh somebody
    downloaded, imported, repaired and checked could not afterwards be found,
    searched, listed or opened again.
    """
    imports = [e for e in entries if e.origin == "imported"]
    if not imports:
        pytest.skip("nothing has been imported into this checkout")

    for entry in imports:
        assert entry.directory.is_dir()
        assert (entry.directory / library.IMPORT_NAME).is_file(), (
            "%s is listed as imported with no import record" % entry.name
        )


def test_an_import_carries_the_measurements_taken_when_it_arrived(entries):
    """
    Measured at ingest and read back, never re-derived.

    import.json is written with the envelope, volume, triangle and body counts
    from the same measurement code a built part's regression uses. A library
    that recomputed them would be a second opinion about a mesh that has not
    changed - and slow, because it would mean loading every mesh to draw a
    list.
    """
    sized = [e for e in entries if e.origin == "imported" and e.envelope_mm]
    if not sized:
        pytest.skip("no imported mesh here recorded an envelope")

    for entry in sized:
        assert len(entry.envelope_mm) == 3
        assert all(v > 0 for v in entry.envelope_mm), (
            "%s has a zero dimension: %s" % (entry.name, entry.envelope_mm)
        )

        # A VOLUME IS ONLY MEANINGFUL ON A CLOSED MESH, and this used to
        # assert every import had one. It held for as long as every import in
        # this library happened to be watertight, and broke the first time a
        # real download was brought in: a laptop riser off Printables, open
        # at the seams like a great many published models.
        #
        # imports.py is explicit that on an open mesh trimesh still returns a
        # number and that number means nothing, so the recorded volume is
        # left at zero rather than filled with a figure nobody can use. That
        # is rule 29 working, and a test asserting the opposite was asserting
        # a snapshot of a tidy library rather than the rule.
        # WATERTIGHTNESS IS IN THE IMPORT RECORD, not on the library entry -
        # the entry carries what a LIST needs and this is a fact about the
        # mesh. Read from the same file the measurements came from.
        import json as _json

        record = _json.loads((Path(entry.directory) / "import.json").read_text())
        if record.get("watertight"):
            assert entry.volume_cm3 > 0, (
                "%s is closed and has no volume recorded" % entry.name
            )
        else:
            assert not entry.volume_cm3, (
                "%s is not closed, so any volume on it is a number that means "
                "nothing: %r" % (entry.name, entry.volume_cm3)
            )


def test_an_import_is_findable_by_the_name_the_FILE_had(entries):
    """
    Somebody looks for what they downloaded, not what we called the directory.

    "LCD-knob.stl" is the thing they recognise; `lcd-knob` is this program's
    idea of a directory name. Searching only the directory name means the
    search fails for the one kind of entry whose real name is written down.
    """
    named = [e for e in entries if e.origin == "imported" and e.source_name]
    if not named:
        pytest.skip("no imported mesh here recorded its source filename")

    entry = named[0]
    stem = entry.source_name.rsplit(".", 1)[0]
    hits = library.search(stem.lower(), entries)
    assert any(e.name == entry.name for e in hits), (
        "%r did not find the import it came from" % stem
    )


def test_a_part_and_an_import_are_told_apart(entries):
    """
    The distinction decides which tools a screen offers.

    A part has a spec, so a sentence rebuilds it. An import is somebody else's
    triangles: it can be hollowed, cut and scaled, and it cannot be described
    into a different shape because there is no parametric model to change.
    """
    for entry in entries:
        assert entry.origin in ("built", "imported")
        if entry.origin == "imported":
            assert entry.spec_path is None, (
                "%s is marked imported but has a spec - it would be offered "
                "changes it cannot make" % entry.name
            )
        else:
            assert (entry.spec_path is not None or entry.draft_path is not None), (
                "%s is marked built with neither a spec nor a draft" % entry.name
            )


# ---------------------------------------------------------------------------
# reading a big library without reading it all again every time
# ---------------------------------------------------------------------------


def _model(root, name, width=40, kind="spec"):
    """One directory that counts as a part, written the shortest honest way."""
    import json as _json

    directory = root / name
    (directory / "out").mkdir(parents=True, exist_ok=True)
    (directory / "out" / "m.stl").write_bytes(b"solid x\nendsolid x\n")
    if kind == "import":
        (directory / "import.json").write_text(_json.dumps({
            "name": name, "source_name": "%s.stl" % name,
            "envelope_mm": [width, 20, 10], "volume_cm3": 3.2,
            "bodies": 1, "triangles": 500, "watertight": True}))
    else:
        (directory / "spec.yaml").write_text(
            "name: %s\nlevel: 2\nmaterial: petg\nnozzle_mm: 0.4\nlayer_mm: 0.2\n"
            "print_axis: z\nops:\n- {op: rounded_prism, width_mm: %d, "
            "depth_mm: 20, height_mm: 6}\n" % (name, width))
    return directory


def test_a_directory_that_has_not_moved_is_not_read_again(tmp_path):
    """
    A SEARCH RUNS ON EVERY KEYSTROKE. At forty parts re-reading the lot costs
    nothing; at a thousand it is most of a second per letter typed, and the
    gallery this is for is one somebody has put hundreds of downloaded models
    into.

    Measured by counting reads rather than by timing, because a timing
    assertion on a loaded machine is a test that fails for the wrong reason.
    """
    from whittle import library

    for i in range(5):
        _model(tmp_path, "m%d" % i)

    library.forget()
    reads = []
    real = library.read_entry
    library.read_entry = lambda d: (reads.append(Path(d).name), real(d))[1]
    try:
        first = library.scan([tmp_path])
        assert len(first) == 5
        assert len(reads) == 5 + 1, reads      # the five, plus the root itself

        reads.clear()
        again = library.scan([tmp_path])
        assert len(again) == 5
        assert reads == [], "a library that had not changed was read again"
    finally:
        library.read_entry = real


def test_a_part_rewritten_in_place_is_noticed(tmp_path):
    """
    THE WAY A CACHE LIKE THIS GOES WRONG.

    A directory's mtime moves when a file is created or removed inside it and
    NOT when an existing file's contents change. Fingerprinting the directory
    alone would mean a rebuild that rewrites spec.yaml over itself - which is
    what setting a number does - leaves the gallery showing the old part for
    ever, with no way to notice and nothing to blame.
    """
    from whittle import library

    _model(tmp_path, "one", width=40)
    library.forget()
    assert library.scan([tmp_path])[0].params or True   # read it once

    spec = tmp_path / "one" / "spec.yaml"
    spec.write_text(spec.read_text().replace("name: one", "name: renamed"))

    after = library.scan([tmp_path])
    assert [e.name for e in after] == ["renamed"], (
        "a spec rewritten in place was served from the cache: %r"
        % [e.name for e in after]
    )


def test_a_part_that_gains_its_stl_is_noticed(tmp_path):
    """
    The other half: a build writes its exports into out/ after the spec is
    already there. A gallery that missed that would show a part with no
    thumbnail and no download for as long as the process lived.
    """
    from whittle import library

    directory = _model(tmp_path, "two")
    (directory / "out" / "m.stl").unlink()
    library.forget()
    assert library.scan([tmp_path])[0].stl is None

    (directory / "out" / "two.stl").write_bytes(b"solid x\nendsolid x\n")
    assert library.scan([tmp_path])[0].stl is not None, (
        "a part that gained its STL was served from the cache without one"
    )


def test_a_part_that_is_deleted_leaves_the_library(tmp_path):
    from whittle import library
    import shutil

    _model(tmp_path, "keep")
    _model(tmp_path, "gone")
    library.forget()
    assert len(library.scan([tmp_path])) == 2

    shutil.rmtree(tmp_path / "gone")
    assert [e.name for e in library.scan([tmp_path])] == ["keep"]
