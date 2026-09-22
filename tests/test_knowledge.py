"""
What the machine has measured, offered back when something like it is asked
for.

THE FAILURE THIS GUARDS AGAINST IS THE SUBTLE ONE. A knowledge base that
improves prompts is easy to write and easy to get quietly wrong: the moment
it blends, averages or infers a dimension, every number downstream is one
nobody measured and nobody can trace, which is what rules 9, 13 and 14 exist
to stop. So most of what is asserted here is about what it must NOT do.
"""

from __future__ import annotations

import json

import pytest

from whittle import knowledge


def _import(root, name, envelope, tags=(), note="", volume=3.0, bodies=1):
    """One measured import on disk, written the shortest honest way."""
    directory = root / name
    (directory / "out").mkdir(parents=True, exist_ok=True)
    (directory / "out" / "m.stl").write_bytes(b"solid x\nendsolid x\n")
    (directory / "import.json").write_text(json.dumps({
        "name": name, "source_name": "%s.stl" % name,
        "note": note, "tags": list(tags),
        "envelope_mm": list(envelope), "volume_cm3": volume,
        "bodies": bodies, "triangles": 900, "watertight": True}))
    return directory


@pytest.fixture
def shelf(tmp_path):
    """A small library of measured things, with two of the same kind in it."""
    from whittle import library

    _import(tmp_path, "phone_stand_wedge", (78, 62, 95), note="a phone stand")
    _import(tmp_path, "phone_stand_tall", (70, 70, 120), note="a phone stand")
    _import(tmp_path, "cable_clip", (20, 12, 8), note="a clip for a cable")
    _import(tmp_path, "planter_pot", (90, 90, 70), note="a pot for a plant")
    library.forget()
    return knowledge.index([tmp_path])


def test_it_finds_the_things_a_request_is_about(shelf):
    hits = knowledge.closest("a phone stand", shelf)
    assert hits, "nothing matched a request the library plainly answers"
    assert {h.name for h in hits} >= {"phone_stand_wedge", "phone_stand_tall"}
    # THE CLOSEST FIRST. Both are phone stands; the clip is not, and if it
    # ranks alongside them the ordering is carrying no information.
    assert hits[0].name.startswith("phone_stand")


def test_a_request_unlike_anything_here_gets_nothing(shelf):
    """
    AN EMPTY ANSWER IS A REAL ANSWER.

    The alternative - handing over the nearest thing whatever it is - means
    a request for a dragon is told how big a cable clip is, presented as
    evidence. That is worse than no priors, because it reads as measured.
    """
    assert knowledge.closest("an articulated dragon", shelf) == []
    assert knowledge.facts_for("an articulated dragon", shelf) == {}


def test_every_figure_says_where_it_came_from(shelf):
    """
    Rule 13 and rule 14 in one line: a dimension with no source is exactly
    the kind of number this must never produce. Anybody reading the spec
    afterwards has to be able to chase a figure back to the mesh it was
    measured off.
    """
    for item in knowledge.closest("a phone stand", shelf):
        line = item.line()
        assert item.name in line
        assert "mm" in line
        assert item.origin in ("made here", "brought in")
        assert item.origin in line
        assert item.directory, "%s cannot be traced to a directory" % item.name


def test_it_never_invents_a_dimension(shelf):
    """
    THE ONE THAT MATTERS.

    Two phone stands measure 78 x 62 x 95 and 70 x 70 x 120. A knowledge
    base that "knows how big a phone stand is" would offer their average -
    74 x 66 x 107 - which is a number nobody measured, off an object that
    does not exist, and no rule in this codebase permits it.

    Every figure that leaves here must be one that is on disk.
    """
    measured = {tuple(item.envelope_mm) for item in shelf}
    for item in knowledge.closest("a phone stand", shelf):
        assert tuple(item.envelope_mm) in measured, (
            "%s reports %s, which is not the measurement of anything here"
            % (item.name, item.envelope_mm)
        )

    said = json.dumps(knowledge.facts_for("a phone stand", shelf))
    for invented in ("74", "66", "107"):
        assert invented not in said, (
            "an averaged dimension (%s) reached the model: %s" % (invented, said)
        )


def test_what_the_model_is_told_says_these_are_other_objects(shelf):
    """
    A model handed "phone_stand 78 x 62 x 95 mm" with no framing copies it,
    and the request was for a DIFFERENT phone stand. The caveat travels with
    the numbers rather than beside them - the same rule reference_facts
    follows for pixels.
    """
    facts = knowledge.facts_for("a phone stand", shelf)
    assert facts["similar_things_already_measured"]
    guidance = facts["how_to_use_them"].lower()
    assert "other objects" in guidance
    assert "not the part being asked for" in guidance
    assert "do not copy" in guidance


def test_one_measurement_per_thing_not_one_per_build(tmp_path):
    """
    A refine writes a new part and leaves the old one alone, so four tweaks
    to a birdhouse are four directories with one name. As four pieces of
    evidence they read as four independent observations, and they fill every
    slot - so a request for a birdhouse saw one object four times.
    """
    from whittle import library

    for suffix in ("", "_2", "_3", "_4"):
        _import(tmp_path, "birdhouse%s" % suffix, (348, 165, 175))
    # NAMED THE SAME, because that is what a rebuild chain looks like: the
    # spec name is what the entry reports, and the directory differs.
    for directory in tmp_path.iterdir():
        meta = directory / "import.json"
        record = json.loads(meta.read_text())
        record["name"] = "birdhouse"
        meta.write_text(json.dumps(record))
    library.forget()

    shelf = knowledge.index([tmp_path])
    assert len(shelf) == 1, (
        "one object measured four times came back as %d pieces of evidence"
        % len(shelf)
    )


def test_a_library_that_cannot_be_read_costs_priors_not_the_build():
    """
    Rule 11: the system stays fully usable with nothing else working. This
    is context that improves an answer, so a failure to gather it is a
    reason to build without it and never a reason to refuse.
    """
    from whittle.agent.loop import _measured_neighbours

    assert _measured_neighbours("a bracket") is not None
    assert isinstance(_measured_neighbours(""), list)


def test_the_prompt_carries_the_evidence_and_the_caveat():
    """
    The block reaches the text the model actually reads, or none of this
    does anything.
    """
    from whittle.agent import prompts

    lines = ["phone_stand_wedge  78 x 62 x 95 mm  brought in"]
    for text in (
        prompts.build_user_prompt("a phone stand", "petg", 0.4, 0.2, similar=lines),
        prompts.build_dsl_prompt("a phone stand", "petg", 0.4, 0.2, similar=lines),
    ):
        assert "phone_stand_wedge  78 x 62 x 95 mm  brought in" in text
        assert "OTHER objects" in text
        assert "Do NOT copy their dimensions" in text

    # AND NOTHING AT ALL WHEN THERE IS NOTHING. An empty heading over an
    # empty list is a prompt telling the model it has evidence it has not.
    bare = prompts.build_dsl_prompt("a dragon", "petg", 0.4, 0.2, similar=[])
    assert "MEASURED, ON THIS MACHINE" not in bare


# ---------------------------------------------------------------------------
# a public corpus, as more evidence
# ---------------------------------------------------------------------------


def _corpus(tmp_path, rows):
    path = tmp_path / "corpus.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def test_the_corpus_is_read_as_evidence_with_its_provenance(tmp_path):
    """
    Thingi10K is 10,000 models people actually printed, published as a
    dataset with per-model licences. It is read as more of the same kind of
    evidence - measured objects with names - and every line says it came
    from somebody else.
    """
    path = _corpus(tmp_path, [
        {"file_id": 1, "name": "Desk phone stand", "tags": ["phone", "stand"],
         "category": "gadgets", "envelope_mm": [80, 70, 100],
         "volume_cm3": 42.0, "license": "CC BY", "author": "somebody"},
    ])
    found = knowledge.corpus(path)
    assert len(found) == 1
    assert found[0].origin == "printed by somebody else"
    assert "thingi10k:1" in found[0].directory


def test_one_entry_per_thing_not_per_file(tmp_path):
    """
    A Thingiverse "thing" is often several files - a body, a lid, three
    variants - all carrying the same name. Handed over as evidence they read
    as several independent observations, and one model filled every slot of
    a four-slot answer on its own.
    """
    rows = [{"file_id": i, "name": "Filament spool holder", "tags": ["spool"],
             "envelope_mm": [200, 200, 60], "volume_cm3": 90.0} for i in range(4)]
    assert len(knowledge.corpus(_corpus(tmp_path, rows))) == 1


def test_a_negative_volume_is_an_inverted_mesh_and_not_a_measurement(tmp_path):
    """
    "Gunny Sacks 103 x 94 x 125 mm  -486.2 cm3" - the faces point inward, so
    the volume integral comes out signed the wrong way. These are real
    uploads and a fifth of them are non-manifold; nothing downstream should
    have to know that, and a negative volume on screen is nonsense.
    """
    path = _corpus(tmp_path, [
        {"file_id": 9, "name": "Gunny Sacks", "envelope_mm": [103, 94, 125],
         "volume_cm3": -486.2},
    ])
    found = knowledge.corpus(path)
    assert len(found) == 1
    assert found[0].volume_cm3 is None
    assert "-486" not in found[0].line()


def test_no_corpus_is_a_normal_state(tmp_path):
    """
    A fresh install has no corpus and works exactly as before: the priors
    come from whatever the person has made or brought in. This only ever
    adds.
    """
    assert knowledge.corpus(tmp_path / "nothing.jsonl") == []


def test_what_is_on_this_machine_wins_a_close_call(tmp_path):
    """
    Asked for "a phone stand", a public corpus offered "Universal
    stand-alone filament spool holder" above this machine's own
    iphone_holder - it matched "stand" inside "stand-alone". A thing
    somebody here made or chose to keep is better evidence of what they
    mean.
    """
    # A GENUINE TIE: both are called "stand", both match the one word the
    # request offers, and nothing else separates them. The first version of
    # this test compared two entries matching DIFFERENT words and asserted
    # the local one won - which the ranking does not promise and should not:
    # matching "phone" and matching "stand" are two different claims about
    # "a phone stand", and the score is what weighs them.
    mine = knowledge.Known(
        name="stand", origin="made here", directory="parts/x",
        envelope_mm=(120, 60, 50), words="stand")
    theirs = knowledge.Known(
        name="stand", origin="printed by somebody else",
        directory="thingi10k:5", envelope_mm=(200, 200, 60), words="stand")

    ranked = knowledge.closest("a stand", [theirs, mine])
    assert ranked[0].origin == "made here", (
        [(k.name, k.origin, k.score) for k in ranked]
    )


def test_but_covering_more_of_the_request_still_wins(tmp_path):
    """
    The other half, and the local preference must not beat it: "a spool
    holder" names two things and the spool holder matches both. A
    preference that exists to settle near-ties had started overruling
    plainly better matches.
    """
    mine = knowledge.Known(
        name="iphone_holder", origin="made here", directory="parts/x",
        envelope_mm=(120, 60, 50), words="iphone_holder phone holder")
    theirs = knowledge.Known(
        name="Universal filament spool holder",
        origin="printed by somebody else", directory="thingi10k:5",
        envelope_mm=(200, 200, 60), words="universal filament spool holder")

    ranked = knowledge.closest("a spool holder", [theirs, mine])
    assert ranked[0].name.endswith("spool holder"), [k.name for k in ranked]
