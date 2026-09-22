"""
The HTTP layer, tested against a real server on a real socket.

NOT against the handler class with a mocked request. The bugs this layer
actually produced were all in the plumbing rather than the logic: a name that
resolved in one route and 404'd in another, an STL glob that looked in the
wrong directory, and a Cache-Control header that made every future upgrade
serve the old interface for an hour. None of those are visible if the socket is
faked away, so the socket is real.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from whittle.web import server as web

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % httpd.server_address[1]
    finally:
        httpd.shutdown()
        httpd.server_close()


def get(url, **kw):
    return urllib.request.urlopen(url, timeout=60, **kw)


def get_json(url):
    with get(url) as response:
        return json.loads(response.read())


def status_of_post(url, payload) -> int:
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def status_of(url) -> int:
    try:
        with get(url) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


# ---------------------------------------------------------------------------
# the page itself
# ---------------------------------------------------------------------------


def test_the_page_and_its_assets_are_served(base_url):
    for path in ("/", "/static/app.css", "/static/app.js"):
        with get(base_url + path) as response:
            assert response.status == 200
            assert len(response.read()) > 200, "%s came back empty" % path


def test_the_interface_is_not_cached_but_the_renders_are(base_url):
    """
    The upgrade bug. Caching app.js for an hour means someone who updates
    whittle keeps being served the old interface, with nothing to tell them
    that is what is happening. Renders may be cached hard - a built part's
    geometry never changes, because a refinement writes a new part.
    """
    with get(base_url + "/static/app.js") as response:
        assert "no-cache" in response.headers.get("Cache-Control", "")
    with get(base_url + "/") as response:
        assert "no-cache" in response.headers.get("Cache-Control", "")


def test_health_reports_the_pinned_printer(base_url):
    data = get_json(base_url + "/api/health")
    assert data["printer"]["name"] == "Creality i7"
    assert data["bed"]["height_mm"] == 255.0, "the bed is not a cube - 255, not 260"
    assert "petg" in data["materials"]


def test_health_reports_the_nozzle_every_verdict_is_measured_against(base_url):
    """
    The number that decides whether a feature is printable, before a part is
    asked for.

    A part's stored checks carry the nozzle they were taken with, and `drift`
    compares that against the profile as it stands - so the figure was reachable
    only by opening a part that had already been built. The phone's first screen
    says what a request will be measured against BEFORE it is made, which needs
    the current setting rather than a historical one.
    """
    data = get_json(base_url + "/api/health")
    settings = data["print"]
    assert settings["nozzle_mm"] == 0.4
    assert settings["layer_mm"], "the layer height is what a verdict is read at"


# ---------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------


def test_the_library_lists_parts_with_their_sizes(base_url):
    data = get_json(base_url + "/api/parts")
    parts = data["parts"]
    assert parts, "no parts listed at all"
    sized = [p for p in parts if p.get("size_mm")]
    assert sized, (
        "every part came back with no size. The library calls this field "
        "envelope_mm, not bbox_mm, and reading the wrong one looks exactly "
        "like a part that has never been built."
    )


def test_a_part_resolves_by_both_of_its_names(base_url):
    """
    THE SAME PART HAS TWO NAMES. parts() calls it by its directory - "keyring" -
    and library() calls it by its spec name - "loop_keyring". Both get shown to
    people and both get linked, so both have to work.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    entry = next((p for p in parts if p.get("dir") and p["dir"] != p["name"]), None)
    if entry is None:
        pytest.skip("no part in this library whose two names differ")

    for name in (entry["name"], entry["dir"]):
        assert status_of("%s/api/part/%s" % (base_url, name)) == 200, \
            "%r did not resolve" % name


def _first_built(base_url: str) -> dict:
    """
    A part that actually has geometry behind it.

    NOT parts[0]. The library is newest-first and it lists DRAFTS too - a run
    that failed hands off a spec.draft.yaml with no mesh, which is right, it
    is something you started. So the newest entry is whatever was attempted
    last, and taking it on faith made this test pass or fail depending on
    what had been generated that afternoon. It failed the first time a failed
    generate happened to be the most recent thing in the library.

    AND NOT AN IMPORT EITHER, for the same reason one step on. Somebody
    else's mesh IS built - it has geometry, it renders, it measures - and it
    has no spec, no assumptions and no height map, because nothing here
    described it. Callers of this want a part WHITTLE BUILT: they ask it for
    its spec, its dimensions, its verdict. This failed the first time a real
    STL was imported, which on a product whose whole point is bringing models
    in is going to be most afternoons.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    built = [p for p in parts
             if p.get("built") is not False and p.get("origin") != "imported"]
    assert built, "the library has no part whittle built to ask about"
    return built[0]


def test_a_part_serves_what_it_ASSUMED_rather_than_what_it_was_told(base_url):
    """
    Rule 14's named parameters, reachable from a part on disk.

    THIS IS THE ORDINARY REQUEST, NOT AN EDGE ONE. Nobody opens this and types
    "a bracket for a 35 mm pipe, 4 mm thick, two M4 holes 60 mm apart". They
    type "a bracket". Every number that comes back was therefore chosen rather
    than given, each is an Assumption with the reason it had to be chosen, and
    that list is the whole of what there is to change afterwards.

    It was unreachable twice over. `_part_payload` read the list off the
    VERIFY report, which has no such field and never has - so the getattr
    default swallowed it and every client drew an assumptions panel that could
    not render. And nothing wrote them to run.json, so a part opened from the
    library - the only way anybody sees a part again - had none either.

    The field is asserted present on every built part. Whether a given part
    assumed anything depends on what it is, so an empty list is a legitimate
    answer and only the SHAPE is checked here.
    """
    from whittle.spec.schema import Assumption

    data = get_json("%s/api/part/%s" % (base_url, _first_built(base_url)["dir"]))

    assumed = data.get("assumptions")
    assert assumed is not None, (
        "a built part does not report its assumptions at all - rule 14's "
        "marked parameters are not reachable from the library"
    )
    assert isinstance(assumed, list)

    for item in assumed:
        assert isinstance(item, dict), (
            "an assumption came back as %r. It used to be str() of a Pydantic "
            "model, which put name='corner_r_mm' value=6.0 units='mm' on a "
            "phone screen and gave no client a value it could act on."
            % type(item).__name__
        )
        assert item["name"], "an assumption with no parameter name names nothing"
        assert item["value"] is not None, "an assumption with no value is not one"
        # Rule 14's own words: the reason is required. A number with no reason
        # beside it is the invented one rule 29 exists to stop.
        assert item["why"], "%s was assumed with no reason given" % item["name"]
        # The keys are the model's own, so renaming a field there is caught
        # here rather than by a blank panel on a phone.
        assert set(item) == set(Assumption.model_fields), (
            "assumption keys %s do not match the Assumption model" % sorted(item)
        )


def test_the_height_map_can_be_LOOKED_AT(base_url):
    """
    Rule 27 and rule 28, which had no route between them.

    "The height map is the primary geometry-verification visual, not the shaded
    render" - a flat-shaded renderer cannot show a recess whose floor shares a
    normal with the surrounding face. And "no part is done until whittle verify
    passes and a height map has been generated and looked at."

    Every part on disk has had one since it was built. Neither client could
    show one. The only way to reach a PNG was /api/part/<n>/file/png, which
    globs out/*.png, takes whichever sorts FIRST and serves it as an
    attachment - so it happened to be the height map, by alphabet, offered as a
    download rather than as something to look at.
    """
    name = _first_built(base_url)["dir"]

    for kind in ("heightmap", "section", "preview"):
        url = "%s/api/part/%s/render/%s" % (base_url, name, kind)
        if status_of(url) == 404:
            # A part built before a given render was written genuinely has
            # none, and saying so is the right answer. What must not happen is
            # a 200 with nothing in it.
            continue
        with get(url) as response:
            body = response.read()
            assert response.headers.get("Content-Type") == "image/png"
            assert body[:8] == b"\x89PNG\r\n\x1a\n", "%s is not a PNG" % kind
            # INLINE, NOT AN ATTACHMENT. An <Image> cannot draw a download.
            assert not response.headers.get("Content-Disposition"), (
                "%s is served as an attachment, so no screen can show it" % kind
            )

    assert status_of("%s/api/part/%s/render/heightmap" % (base_url, name)) == 200, (
        "a built part has no height map to look at, which rule 28 makes a "
        "condition of the part being done"
    )


def test_an_unknown_render_says_what_there_is(base_url):
    """A 404 that names the alternatives, rather than one that just refuses."""
    name = _first_built(base_url)["dir"]
    import urllib.error

    try:
        with get("%s/api/part/%s/render/nonsense" % (base_url, name)):
            raise AssertionError("an unknown render was served")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
        message = json.loads(exc.read())["error"]
        for kind in ("heightmap", "section", "preview"):
            assert kind in message, "the refusal does not mention %s" % kind


def test_an_imported_mesh_serves_what_was_measured_when_it_arrived(base_url):
    """
    Opening an import returned a name and a frame count and nothing else.

    `_one_part` reads spec.yaml, run.json and regression.json. An import writes
    none of those - it writes import.json - so the screen whose job is to show
    a part's size, volume and piece count showed none of them, on the one kind
    of part where every figure was measured at ingest and sitting on disk.

    The library list had been reading that file all along. The part itself had
    not.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    imported = [p for p in parts if p.get("origin") == "imported"]
    if not imported:
        pytest.skip("nothing has been imported into this checkout")

    data = get_json("%s/api/part/%s" % (base_url, imported[0]["dir"]))

    assert data.get("origin") == "imported", (
        "an imported mesh does not say so, and a client cannot then withhold "
        "the controls it has no spec for"
    )
    assert data.get("size_mm"), "no envelope on an import that recorded one"
    assert len(data["size_mm"]) == 3
    assert data.get("has_stl") is True


def test_a_part_built_here_says_it_was(base_url):
    """
    The flag has to be present on BOTH kinds or a client cannot branch on it.

    An absent `origin` is indistinguishable from "imported and not reported",
    and the client's fallback is to treat it as built - which is the safe way
    round only if built parts actually say so.
    """
    data = get_json("%s/api/part/%s" % (base_url, _first_built(base_url)["dir"]))
    assert data.get("origin") in ("built", "imported")


def test_a_part_carries_its_spec_and_its_measured_size(base_url):
    data = get_json("%s/api/part/%s" % (base_url, _first_built(base_url)["name"]))

    # load_spec returns (PartSpec, base_dir). Handing the tuple to the
    # serialiser produced "{}" and a Spec tab that looked empty.
    assert data.get("spec"), "the spec came back empty"
    assert data["spec"].get("name"), "the spec has no name in it"
    assert data.get("size_mm"), "no size"


def test_a_draft_says_it_has_no_mesh_rather_than_looking_broken(base_url):
    """
    The other half of the same fact, and a real bug on the phone: the app
    asked a draft for a render, got a guaranteed 404, and showed a broken
    card. The library payload has always said `built`, so a client never has
    to guess - and a draft must not claim an STL it does not have.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    drafts = [p for p in parts if p.get("built") is False]
    if not drafts:
        pytest.skip("no draft in the library to check")

    data = get_json("%s/api/part/%s" % (base_url, drafts[0]["name"]))
    assert data.get("has_stl") is not True, (
        "a draft reported an STL; a client will ask for a render and get a 404"
    )


def test_a_stored_part_serves_the_verdict_it_was_given(base_url):
    """
    THE VERDICT WAS ON DISK THE WHOLE TIME.

    This route used to answer with no verdict at all, and both clients printed
    "not re-checked" over every part, on the stated grounds that nothing
    records one and that re-verifying costs as long as building. Both were
    false: every part built through the pipeline writes run.json and run.json
    holds the entire verify report, and a re-verify of a real part measured
    0.3s against that same part's recorded build time of 151s.

    What is still forbidden is inventing one. A part with no run.json - an
    import, or one made before whittle kept one - carries no `checks` key at
    all, which is a real "not known" rather than a manufactured PASS.
    """
    name = _first_built(base_url)["name"]
    data = get_json("%s/api/part/%s" % (base_url, name))

    checks = data.get("checks")
    if checks is None:
        # Legitimate: this part has no run.json. Then it must claim nothing.
        assert "verdict" not in data
        pytest.skip("%s predates run.json, so there is nothing stored to serve"
                    % name)

    assert checks["verdict"] in ("PASS", "PASS, with warnings", "FAIL")
    assert isinstance(checks["ok"], bool)
    assert checks["source"] == "stored"

    # PROVENANCE, OR IT IS A REMEMBERED TICK. A verdict with no date and no
    # profile behind it is exactly what this program refuses to show.
    assert checks["checked_at"] > 0
    assert "drift" in checks

    # AND A MEASURED VALUE ON EVERY LINE. A status with no number beside it is
    # a green tick, which is what the checks panel exists not to be.
    assert checks["lines"], "the verdict came with no measured checks"
    for line in checks["lines"]:
        assert line["name"]
        assert line["value"] != ""
        assert line["status"] in ("pass", "warn", "fail", "info")


# The patterns both clients light their stage list from - mobile/lib/
# building_screen.dart kStages and the web's STAGES. Repeated here on purpose:
# they are a CONTRACT between the engine's words and two front ends, and the
# thing that broke was the engine silently not saying two of them.
STAGE_PATTERNS = ["using", "template", "building geometry", "verify", "export"]


def test_every_stage_the_clients_show_can_actually_be_reached(base_url):
    """
    TWO OF THE FIVE STAGES WERE DECORATION.

    Both clients show a five-stage list and both promise in their own comments
    that it is driven by real job status and never by a timer. But the engine
    emitted nothing for verification and nothing for the exports, so the last
    two stages could not light from an event: the bar sat at three of five for
    the whole build and then jumped to five when the run finished.

    A progress bar that is two thirds honest is worse than a four-stage one,
    because the dishonest third is invisible. This drives the server's event
    translation with the kinds the engine really emits and checks that every
    pattern the clients match on comes out of it.
    """
    from whittle import api

    class FakeReport:
        verdict = "PASS, with warnings"

    def fake_generate(request, **kwargs):
        emit = kwargs["on_event"]

        class Profile:
            model_primary = "qwen2.5-coder:7b"
            name = "laptop"

        emit("profile", Profile())
        emit("escalate", "no template claims this")
        emit("building", None)
        emit("verified", FakeReport())
        emit("exporting", "parts/thing")
        return api.GenerateResult(ok=False, message="stopped for the test")

    real = api.generate
    api.generate = fake_generate
    try:
        job = web._start_job("generate", "a thing",
                             web._generate_work("a thing", "petg", None))
        for _ in range(400):
            if job.done:
                break
            time.sleep(0.05)
    finally:
        api.generate = real

    notes = " | ".join(e.get("text", "") for e in job.events
                       if e.get("kind") == "note").lower()
    for pattern in STAGE_PATTERNS:
        assert pattern in notes, (
            "stage %r can never light: nothing the engine emits says it. "
            "The notes were: %s" % (pattern, notes)
        )

    # AND THE VERDICT TRAVELS WITH THE STAGE. "Ran your printer checks" that
    # does not say what they found is the green tick this program refuses to
    # show.
    assert "pass, with warnings" in notes


def test_an_internal_event_name_never_leaks_into_the_log(base_url):
    """
    The fallback branch printed str(kind) for anything unhandled, so a user
    watching a build was shown "measurement_rejected" - an internal
    identifier, in the one log they read, with nothing they can do about it.
    """
    from whittle import api

    def fake_generate(request, **kwargs):
        emit = kwargs["on_event"]
        emit("measurement_rejected", {"entrance_dia_mm": 41.2})
        emit("some_future_event_nobody_wrote_a_line_for", object())
        return api.GenerateResult(ok=False, message="stopped for the test")

    real = api.generate
    api.generate = fake_generate
    try:
        job = web._start_job("generate", "a thing",
                             web._generate_work("a thing", "petg", None))
        for _ in range(400):
            if job.done:
                break
            time.sleep(0.05)
    finally:
        api.generate = real

    notes = [e.get("text", "") for e in job.events if e.get("kind") == "note"]
    assert not any("some_future_event" in n for n in notes), notes
    # A rejected measurement IS worth saying, in words, with the value in it.
    assert any("rejected from the image" in n and "41.2" in n for n in notes), notes


def test_a_photo_reaches_the_model_as_facts_and_not_as_a_measurement(base_url):
    """
    THE BUG THIS PINS COST A REAL PHOTO AND A REAL WAIT.

    generate() takes two different things. `facts=` is a dict read off a
    reference that reaches the model as CONTEXT. `measurement=` is an OBJECT
    whose values are applied to matching parameters afterwards, and generate
    calls .as_facts() on it.

    The server passed api.measure_image's dict into the second slot. Every
    generate with a photo attached died on "'dict' object has no attribute
    'as_facts'" before it built anything - so image-to-part worked from the
    command line and nowhere else, on the one device that has a camera in it.

    No model is called here: api.generate is replaced, because what is being
    checked is which argument the server fills.
    """
    from whittle import api

    seen = {}

    def fake_generate(request, **kwargs):
        seen.update(kwargs)
        seen["request"] = request
        return api.GenerateResult(ok=False, message="stopped for the test")

    real = api.generate
    api.generate = fake_generate
    try:
        work = web._generate_work("a cradle for this", "petg",
                                  str(ROOT / "reference" / "loop_render_650x855.png"))
        job = web._start_job("generate", "a cradle for this", work)
        for _ in range(400):
            if job.done:
                break
            time.sleep(0.05)
    finally:
        api.generate = real

    assert job.done, "the job never finished"
    assert "facts" in seen, "the photo did not reach the model at all"
    assert isinstance(seen["facts"], dict)
    # THE PIXEL CAVEAT TRAVELS WITH THE NUMBERS. A model handed "638 wide"
    # with no note can read it as millimetres and build a part six times too
    # big, which is a wrong part with nothing on screen to say so.
    assert "pixel" in seen["facts"]["note"]
    assert seen.get("measurement") is None, (
        "the dict went back into the measurement slot, which is the crash"
    )


def test_a_photo_that_cannot_be_measured_still_builds_from_the_words(base_url):
    """
    A photo that separates nothing is not a reason to refuse the request -
    the sentence still describes a part. It is a reason to SAY so, in the log
    the user is watching, and carry on.
    """
    from whittle import api

    seen = {}

    def fake_generate(request, **kwargs):
        seen.update(kwargs)
        return api.GenerateResult(ok=False, message="stopped for the test")

    real = api.generate
    api.generate = fake_generate
    try:
        work = web._generate_work("a bracket", "petg", "/nowhere/at/all.png")
        job = web._start_job("generate", "a bracket", work)
        for _ in range(400):
            if job.done:
                break
            time.sleep(0.05)
    finally:
        api.generate = real

    assert job.done
    notes = [e.get("text", "") for e in job.events if e.get("kind") == "note"]
    assert any("could not measure" in n for n in notes), notes
    # It still went to the model, with no facts rather than no run.
    assert "facts" in seen and seen["facts"] is None


def test_a_draft_carries_why_it_did_not_build(base_url):
    """
    A DRAFT WAS A DEAD END, AND IT WAS THE WORST ONE IN THE APP.

    The library lists drafts, correctly - a run that gave up is still
    something you started. But opening one asked for a turntable frame of a
    part with no mesh, got a 404, and showed a screen with no size, no
    checks and no exports: the screen you land on after a failure said
    nothing about the failure.

    Everything was already in run.json. What this pins is that it comes out:
    the request as typed, what was spent on it, and the engine's own
    diagnosis - which for a failed cut carries the measured spans and the
    numbers to change, and is worthless the moment anybody paraphrases it.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    drafts = [p for p in parts if p.get("built") is False]
    if not drafts:
        pytest.skip("nothing in the library has failed to build")

    data = get_json("%s/api/part/%s" % (base_url, drafts[0]["name"]))
    draft = data.get("draft")
    assert draft is not None, "a draft came back with nothing about the run"

    # THE SENTENCE COMES BACK. Without it the retry starts from a blank box,
    # which is the worst possible way to recover from a four-minute failure.
    assert draft["request"], "the draft lost what was asked for"
    assert draft["attempts"] >= 1
    assert draft["elapsed_s"] > 0
    # The engine's own words, or an explicit absence of them - never a
    # paraphrase invented here.
    assert "message" in draft
    assert "spec_draft" in draft


def test_a_part_that_built_carries_no_draft(base_url):
    """
    The counterpart. `draft` present means "there is no mesh and here is
    why"; showing it beside a built part would put a failure notice on a
    part that succeeded.
    """
    name = _first_built(base_url)["name"]
    data = get_json("%s/api/part/%s" % (base_url, name))
    if data.get("has_stl") is False:
        pytest.skip("%s has no mesh on disk" % name)
    assert data.get("draft") is None


def test_a_re_check_runs_for_real_and_says_it_is_current(base_url):
    """
    Re-checking is not a rebuild. No model is called and no geometry is
    composed - the mesh is on disk and the same checks run over it again -
    which is why this is a plain POST with an answer rather than a job.
    """
    name = _first_built(base_url)["name"]
    stored = get_json("%s/api/part/%s" % (base_url, name)).get("checks")

    request = urllib.request.Request(
        "%s/api/part/%s/verify" % (base_url, name), data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            pytest.skip("%s has no mesh on disk to check" % name)
        raise

    fresh = body["checks"]
    assert fresh["source"] == "just now"
    # Nothing has drifted from a check taken this second - that is the whole
    # reason to offer one.
    assert fresh["drift"] == []
    assert fresh["lines"]

    # THE TWO MUST AGREE ABOUT THE GEOMETRY. The mesh is deterministic from
    # the spec, so a fresh check of an unchanged part that disagreed with its
    # stored verdict would mean one of the two was wrong.
    if stored is not None and not stored.get("drift"):
        assert fresh["ok"] == stored["ok"], (
            "a re-check disagreed with the stored verdict on unchanged "
            "geometry: %s then %s" % (stored["verdict"], fresh["verdict"]))


def test_re_checking_something_with_no_mesh_says_so(base_url):
    """
    A draft is a spec with no geometry. Asking to measure it is a real
    request with a real answer - there is nothing on disk to measure - and
    that answer is a sentence, not a 500.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    drafts = [p for p in parts if p.get("built") is False]
    if not drafts:
        pytest.skip("nothing in the library has failed to build")

    request = urllib.request.Request(
        "%s/api/part/%s/verify" % (base_url, drafts[0]["name"]),
        data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            assert False, "a draft was checked, and it has no mesh: %s" % (
                response.read())
    except urllib.error.HTTPError as exc:
        assert exc.code == 409, "expected a refusal, got %d" % exc.code
        message = json.loads(exc.read())["error"]
        assert "no mesh" in message, message


def a_built_part(base_url) -> dict:
    """
    A part with a mesh on disk, or a skip that says why.

    parts/*/out/ is gitignored deliberately - the meshes rebuild from the spec
    in seconds - so a fresh clone has specs and no STLs, and a test that
    assumed otherwise died with a bare StopIteration that said nothing.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    built = [p for p in parts if p.get("built")]
    if not built:
        pytest.skip("no part has been built yet - run `whittle build parts/<name>/spec.yaml`")
    return built[0]


def test_the_stl_downloads(base_url):
    built = a_built_part(base_url)
    with get("%s/api/part/%s/stl" % (base_url, built["name"])) as response:
        body = response.read()
    assert len(body) > 1000
    assert "attachment" in response.headers.get("Content-Disposition", "")


def test_a_turntable_frame_renders_and_is_not_blank(base_url):
    built = a_built_part(base_url)
    url = "%s/api/part/%s/frame/3?w=240" % (base_url, built["name"])
    with get(url) as response:
        assert response.status == 200
        data = response.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "that is not a PNG"

    # A render that is entirely background is a render of nothing, and it looks
    # identical to a working viewer pointed at an empty scene.
    import io

    import numpy as np
    from PIL import Image

    pixels = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
    lit = int((pixels.max(axis=2) > 30).sum())
    assert lit > 500, "only %d lit pixels - the frame is blank" % lit


# ---------------------------------------------------------------------------
# the 3D viewer, and the cache that once served a white silhouette for a week
# ---------------------------------------------------------------------------


def test_the_viewer_page_is_served_with_its_renderer_beside_it(base_url):
    """
    ONE VIEWER PAGE, USED BY BOTH CLIENTS. The phone loads this in a WebView
    and the browser loads the same URL, which is the only way the two show a
    part the same way rather than nearly the same way.

    The script is vendored rather than fetched from a CDN because whittle works
    with the cable out - a viewer that needs unpkg is a viewer that fails in a
    workshop with no signal. So the test is that the page is there AND that
    nothing in it points off this machine.
    """
    with get("%s/static/viewer.html" % base_url) as response:
        assert response.status == 200
        page = response.read().decode("utf-8")

    assert "<model-viewer" in page
    assert "/static/vendor/model-viewer.min.js" in page
    assert "//unpkg.com" not in page and "//cdn." not in page, (
        "the viewer fetches its renderer off this machine"
    )

    with get("%s/static/vendor/model-viewer.min.js" % base_url) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "text/javascript"
        assert len(response.read()) > 100_000, "that is not the renderer"

    # Apache-2.0 requires the licence to travel with the code.
    assert status_of("%s/static/vendor/model-viewer-LICENSE.txt"
                     % base_url) == 200


def test_the_glb_carries_a_material_so_it_is_not_a_white_silhouette(base_url):
    """
    A mesh exported straight out of CadQuery has no material, so every glTF
    viewer applies its own default - which is white, and a white part under a
    neutral environment is a silhouette with no readable form. That is what
    the first working viewer showed, and it looked enough like a bug in the
    viewer to send the search in the wrong direction.
    """
    built = a_built_part(base_url)
    with get("%s/api/part/%s/glb" % (base_url, built["name"])) as response:
        assert response.status == 200
        data = response.read()

    assert data[:4] == b"glTF", "that is not a GLB"

    # glTF's rule for a primitive with NO material is not "pick something
    # sensible": it is white, metallicFactor 1.0 - a mirror. So the check is
    # that a material exists and that it is not metallic, which is the part
    # that actually made the difference on screen.
    import struct

    length, = struct.unpack("<I", data[12:16])
    doc = json.loads(data[20:20 + length])

    materials = doc.get("materials")
    assert materials, "the GLB declares no material - glTF defaults to a mirror"
    pbr = materials[0]["pbrMetallicRoughness"]
    assert pbr["metallicFactor"] == 0.0, "printed plastic is not metal"
    assert 0.3 <= pbr["roughnessFactor"] <= 0.8, (
        "a mirror or a chalkboard; neither shows form"
    )

    # The grey the turntable frames and the desktop viewport already use. The
    # same part must not look like two objects depending on the view.
    red, green, blue, alpha = pbr["baseColorFactor"]
    assert [round(c * 255) for c in (red, green, blue)] == [158, 168, 184]
    assert alpha == 1.0

    # COLOR_0 as well, for a viewer that ignores materials.
    attributes = doc["meshes"][0]["primitives"][0]["attributes"]
    assert "COLOR_0" in attributes


def test_the_glb_url_can_be_versioned_so_the_hard_cache_stays_correct(base_url):
    """
    THE REGRESSION. The GLB is served `immutable, max-age=604800` on the
    argument that it is the mesh and not a picture of it. That argument broke
    the moment the part's grey was baked in: every file's content changed and
    no file's URL did, so a client that had already fetched the colourless one
    kept drawing white for a week with no way to ask for the new bytes.

    The fix is the frames' fix one layer down - the version goes in the query
    string, so a bump is a new URL. The server ignores the parameter on
    purpose: it exists to make the URL different, and the response must not
    depend on reading it.
    """
    assert web.MESH_VERSION >= 2, (
        "MESH_VERSION was not bumped when the GLB gained a baked colour"
    )

    built = a_built_part(base_url)
    plain = "%s/api/part/%s/glb" % (base_url, built["name"])
    versioned = "%s?mv=%d" % (plain, web.MESH_VERSION)

    with get(plain) as response:
        without = response.read()
        cache = response.headers["Cache-Control"]
    with get(versioned) as response:
        with_version = response.read()

    assert with_version == without, "the version changed the response"
    assert "immutable" in cache, (
        "the hard cache was given up instead of being versioned"
    )

    # An unknown parameter must not 404 or 500 the mesh - the whole point is
    # that a future client can bump the number unilaterally.
    assert status_of("%s?mv=99" % plain) == 200


def test_no_response_carries_two_cache_control_headers(base_url):
    """
    A SILENT BUG, WHICH IS WHY IT GETS ITS OWN TEST.

    _send emitted its own Cache-Control and then the caller's, so the GLB went
    out carrying `no-cache` AND `public, max-age=604800, immutable`. A client
    reads a repeated header as one comma-joined list, no-cache wins it, and the
    mesh was refetched on every single look while the code said it was cached
    for a week. Nothing failed, nothing logged, it was just slow - and the
    header the source claimed was being sent was not the header in force.
    """
    built = a_built_part(base_url)
    for path in ("/", "/static/app.css", "/api/health", "/api/parts",
                 "/api/part/%s" % built["name"],
                 "/api/part/%s/glb" % built["name"],
                 "/api/part/%s/frame/1?w=240" % built["name"]):
        with get(base_url + path) as response:
            values = response.headers.get_all("Cache-Control") or []
        assert len(values) <= 1, (
            "%s sends %d Cache-Control headers: %s" % (path, len(values), values)
        )


def test_the_mesh_is_cached_hard_because_its_url_is_versioned(base_url):
    """
    The other half: having stopped sending two, the one that is sent has to be
    the immutable one. A 40 000-face bowl is nearly two megabytes and the
    server walks the mesh to build it, so a second look at the same part must
    cost nothing.
    """
    built = a_built_part(base_url)
    with get("%s/api/part/%s/glb" % (base_url, built["name"])) as response:
        cache = response.headers["Cache-Control"]
    assert "immutable" in cache, cache
    assert "no-cache" not in cache, cache


def test_the_health_reports_the_mesh_version_so_no_client_repeats_it(base_url):
    """
    The viewer page reads this rather than carrying the constant, because a
    number written in Python and again in JavaScript is a number that drifts -
    and the drift here is silent: the page keeps asking for a URL that was
    correct last month.
    """
    state = get_json("%s/api/health" % base_url)
    assert state["mesh_version"] == web.MESH_VERSION
    # Separate from the frames' version on purpose: a new camera angle must
    # not throw away every cached mesh, and a new baked colour must not throw
    # away every cached frame.
    assert "render_version" in state


# ---------------------------------------------------------------------------
# the command line and the parameter schema, which the workspace is built on
# ---------------------------------------------------------------------------


def post(url, payload):
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def test_the_command_line_parses_server_side(base_url):
    """
    ONE PARSER, AND THIS ROUTE IS WHY IT CAN BE ONE. The handoff says the
    command line must genuinely parse and must share the composer's
    vocabulary. Parsed in each client, `wall 3` would mean one thing in the
    browser and another on the phone - the same class of bug as a colour that
    differs between clients, except this one changes geometry.
    """
    parsed = post("%s/api/command" % base_url, {"line": "wall 3"})
    assert parsed["kind"] == "set"
    assert parsed["parameter"] == "wall_mm"
    assert parsed["value"] == 3.0
    # The echo uses the panel's own words, both directions - brief 6.4.
    assert parsed["echo"] == "wall thickness \u2192 3.0 mm"
    # And it carries the sentence that applies the change, so a slider and a
    # typed command cannot ask for different things.
    assert parsed["refine"] == "set wall thickness to 3.0 mm"


def test_a_question_is_answered_from_the_real_profile(base_url):
    """
    `clearance ?` reads this machine's configuration - and says where the
    number came from. Brief 4.3 forbids stating a clearance as if it were
    calibrated when it is a conservative default, because a maker who
    believes a number is measured designs to it.
    """
    parsed = post("%s/api/command" % base_url,
                  {"line": "clearance ?", "material": "petg"})
    assert parsed["kind"] == "ask"
    assert "0.30 mm" in parsed["echo"]
    assert "not from a calibration strip" in parsed["echo"], (
        "a default clearance was reported as though it were measured"
    )


def test_an_unmeasured_clearance_says_so_rather_than_inventing_one(base_url):
    """
    TPU's clearance is deliberately UNSET because nothing measured it, and
    reading an UNSET value raises rather than substituting a guess. The
    command line has to survive that and answer honestly.
    """
    parsed = post("%s/api/command" % base_url,
                  {"line": "clearance ?", "material": "tpu"})
    assert "no measured source" in parsed["echo"]


def test_an_unknown_line_is_a_new_part_and_not_an_error(base_url):
    """
    A command line that only accepts commands is a worse command line: the
    thing a maker most wants to type is a description of a part.
    """
    parsed = post("%s/api/command" % base_url,
                  {"line": "a hinged clamp for a 32 mm pipe"})
    assert parsed["kind"] == "prompt"
    assert parsed["text"] == "a hinged clamp for a 32 mm pipe"


def test_a_command_without_a_line_is_refused_rather_than_guessed(base_url):
    assert status_of_post("%s/api/command" % base_url, {}) == 400
    assert status_of_post("%s/api/command" % base_url, {"line": 7}) == 400
    # Longer than any command line, which is a paste accident rather than a
    # command, and it must not become a two-minute generation.
    assert status_of_post("%s/api/command" % base_url,
                          {"line": "x" * 500}) == 400


def test_refine_reaches_the_agent_instead_of_dying_on_a_type(base_url):
    """
    THE REGRESSION. api.refine takes a loaded PartSpec; this route passed the
    part NAME straight through, so every refine died inside the agent on
    `'str' object has no attribute 'level'`.

    It had never worked. Nothing exercised it until the phone's command line
    ran `wall 3` against a real part - and the web client's refine box had
    been broken in the same way for as long as it had existed.

    THIS TEST DOES NOT RUN A REFINE. A real one calls the model and takes
    minutes on a CPU. What it checks is the boundary that was wrong: a valid
    name is accepted and gets a job, and an unknown one is refused with a
    sentence rather than a type error - which is enough to catch a name being
    handed to something that wants a spec.
    """
    built = a_built_part(base_url)

    accepted = post("%s/api/refine" % base_url,
                    {"name": built["name"], "instruction": "make it taller"})
    assert accepted.get("job"), "a valid part did not start a refine"

    # And the job must not have died immediately on a type error. The work
    # runs on a thread, so this reads the job back rather than the response.
    import time
    for _ in range(20):
        state = get_json("%s/api/job/%s" % (base_url, accepted["job"]))
        message = str((state.get("result") or {}).get("message", ""))
        assert "has no attribute" not in message, (
            "the refine route is still handing a name to something that "
            "wants a spec: %s" % message
        )
        if state.get("done"):
            break
        time.sleep(0.25)


def test_setting_a_number_directly_needs_no_model_and_no_sentence(base_url):
    """
    A slider, which is not a sentence.

    WHY THIS ROUTE EXISTS BESIDE /api/refine. The parser binds a number to a
    field by the words near it, and the obvious phrasing for a slider collides:
    "drain dia 6mm" claims `drain_dia_mm` and `entrance_dia_mm` equally,
    because both own the word "dia" at the same distance from the number. The
    parser does the right thing with that - it asks rather than guessing - and
    the result, as a slider, is a control that moves and changes nothing.

    So a control that already knows which field it is says so directly. Rule 32
    is untouched: English is still the way in, and this is the implementation
    the rule says the parameters are.

    AND NO MODEL. api.refine loads a model profile before it does anything;
    setting a number does not need one, and rule 11 says the system stays fully
    usable with zero model. A slider is exactly where that has to hold.
    """
    built = _first_built(base_url)
    answer = post("%s/api/part/%s/params" % (base_url, built["dir"]),
                  {"values": {"wall_mm": 3.5}})
    job = answer.get("job")
    assert job, "setting a parameter did not start a job"

    import time
    for _ in range(600):
        state = get_json("%s/api/job/%s" % (base_url, job))
        if state.get("done"):
            break
        time.sleep(0.25)
    assert state.get("done"), "the rebuild never finished"

    result = state.get("result") or {}
    if not result.get("ok"):
        # A template that has no wall_mm refuses on the schema, which is a
        # correct answer and a sentence - not a traceback.
        assert result.get("message"), "it failed with nothing to read"
        assert "has no attribute" not in result["message"], result["message"]
        pytest.skip("the newest built part has no wall_mm: %s" % result["message"])

    # A NEW PART, NOT AN OVERWRITE. Editing never destroys the thing being
    # edited, which is what makes the library a history.
    assert result["dir"] != built["dir"], "the rebuild wrote over the original"
    assert result.get("changes"), "it did not say what it changed"
    assert any("wall_mm" in line for line in result["changes"])

    # And it looks like every other part: a stored verdict and its assumptions,
    # so opening it later does not claim it predates the machine recording them.
    fresh = get_json("%s/api/part/%s" % (base_url, result["dir"]))
    assert fresh.get("checks"), "the rebuilt part has no stored verdict"
    assert fresh.get("assumptions") is not None


def test_a_part_built_from_operations_reports_its_own_numbers(base_url):
    """
    SLIDERS FOR A LEVEL-2 PART, which had none.

    A template part gets its controls from the template's parameter model,
    which the app fetches by name. An ops spec has no template, so the app
    asked for a schema, got nothing back and drew no controls - for most of
    what whittle generates. Rule 32 puts English first and says the
    parameters are how it is implemented; there was no implementation to
    reach.

    ADDRESSED BY POSITION, because an ops spec has no parameter names. The
    bounds come off the op models, which only the server can see.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    # NOT AN IMPORT. "No template" is true of somebody else's mesh as well as
    # of a level-2 spec, and an import has no ops to put sliders on - it is
    # triangles. Selecting on that alone picked whichever kind happened to be
    # newest, so this passed or failed depending on what had been imported
    # that afternoon.
    ops_parts = [p for p in parts
                 if p.get("built") is not False
                 and not p.get("template")
                 and p.get("origin") != "imported"]
    if not ops_parts:
        pytest.skip("every built part in the library came from a template")

    data = get_json("%s/api/part/%s" % (base_url, ops_parts[0]["dir"]))
    dimensions = data.get("dimensions")
    assert dimensions, "an ops part reports no numbers to change: %r" % data.get("spec")

    for dimension in dimensions:
        assert re.fullmatch(r"\d+\.(step\.)?[a-z][a-z0-9_]*", dimension["name"]), (
            "%r is not an address" % dimension["name"]
        )
        # THE ENDS HAVE TO BE DRAGGABLE. The schema accepts up to 1000 mm and
        # a slider spanning that cannot pick 8.00 - one pixel is 2 mm. So the
        # ends are scaled off the value and clamped into the real bounds,
        # which come along so nothing has to infer them.
        assert dimension["low"] < dimension["value"] < dimension["high"], dimension
        assert dimension["bound_low"] <= dimension["low"], dimension
        assert dimension["bound_high"] >= dimension["high"], dimension
        # AND NARROW ENOUGH TO PICK A NUMBER WITH. The ends are a quarter and
        # four times the value, so the span is under four times it - a 40 mm
        # side drags between 10 and 160. Left at the schema's own 0..1000 the
        # control is a lottery, and that is what this asserts against: an
        # earlier version of this test passed with exactly that bug.
        assert dimension["high"] - dimension["low"] <= dimension["value"] * 4, (
            "a slider spanning %g..%g cannot pick %g: %r"
            % (dimension["low"], dimension["high"], dimension["value"], dimension)
        )
        assert dimension["value"] > 0, (
            "a number at zero has nothing to scale a range from and must not "
            "be offered as a slider: %r" % dimension
        )


def test_setting_an_addressed_number_rebuilds_an_ops_part(base_url):
    """
    The other half: a control that knows its address changes the part.

    NO MODEL AND NO SENTENCE, same as the template route - rule 11 says the
    system stays usable with zero model and a slider is where that has to
    hold. A NEW PART, not an overwrite, because editing never destroys the
    thing being edited.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    # NOT AN IMPORT. "No template" is true of somebody else's mesh as well as
    # of a level-2 spec, and an import has no ops to put sliders on - it is
    # triangles. Selecting on that alone picked whichever kind happened to be
    # newest, so this passed or failed depending on what had been imported
    # that afternoon.
    ops_parts = [p for p in parts
                 if p.get("built") is not False
                 and not p.get("template")
                 and p.get("origin") != "imported"]
    if not ops_parts:
        pytest.skip("every built part in the library came from a template")

    opened = ops_parts[0]["dir"]
    data = get_json("%s/api/part/%s" % (base_url, opened))
    dimensions = data.get("dimensions") or []
    if not dimensions:
        pytest.skip("that part reports no numbers")

    pick = dimensions[0]
    wanted = round(pick["value"] * 1.25, 2)
    answer = post("%s/api/part/%s/params" % (base_url, opened),
                  {"values": {pick["name"]: wanted}})
    job = answer.get("job")
    assert job, "setting an addressed number did not start a job"

    import time
    for _ in range(600):
        state = get_json("%s/api/job/%s" % (base_url, job))
        if state.get("done"):
            break
        time.sleep(0.25)
    assert state.get("done"), "the rebuild never finished"

    result = state.get("result") or {}
    assert result.get("ok"), result
    assert result["dir"] != opened, "the rebuild wrote over the original"
    assert any(pick["name"] in line for line in result.get("changes") or []), result

    # AND THE NUMBER IS IN THE STORED SPEC, which is the durable artifact - a
    # spec that does not rebuild the stored mesh is the worst thing to leave
    # on disk.
    try:
        fresh = get_json("%s/api/part/%s" % (base_url, result["dir"]))
        moved = [d for d in fresh.get("dimensions") or []
                 if d["name"] == pick["name"]]
        assert moved and moved[0]["value"] == pytest.approx(wanted), (
            "the part was rebuilt without the number that was set: %r" % moved
        )
    finally:
        # CLEAN UP AFTER ITSELF. This test builds a real part into the real
        # library, because that is the only way to prove the route writes a
        # spec that rebuilds. Left behind, every run of the suite adds one -
        # which is how `hinge_2`, `hinge_3` and `hinge_4` ended up in
        # somebody's gallery. The delete route is the one that exists for it.
        post("%s/api/part/%s/delete" % (base_url, result["dir"]), {})


def test_an_address_that_names_nothing_is_a_sentence_not_a_traceback(base_url):
    """
    Rule 32's third clause. An address off the end of the ops list, or a field
    the op does not have, comes back as something a person can read.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    # NOT AN IMPORT. "No template" is true of somebody else's mesh as well as
    # of a level-2 spec, and an import has no ops to put sliders on - it is
    # triangles. Selecting on that alone picked whichever kind happened to be
    # newest, so this passed or failed depending on what had been imported
    # that afternoon.
    ops_parts = [p for p in parts
                 if p.get("built") is not False
                 and not p.get("template")
                 and p.get("origin") != "imported"]
    if not ops_parts:
        pytest.skip("every built part in the library came from a template")

    url = "%s/api/part/%s/params" % (base_url, ops_parts[0]["dir"])
    for address in ("99.width_mm", "0.not_a_field_mm"):
        answer = post(url, {"values": {address: 12}})
        job = answer.get("job")
        assert job, address

        import time
        for _ in range(200):
            state = get_json("%s/api/job/%s" % (base_url, job))
            if state.get("done"):
                break
            time.sleep(0.25)
        result = state.get("result") or {}
        assert result.get("ok") is False, (address, result)
        assert result.get("message"), address
        assert "Traceback" not in result["message"], result["message"]

    # MIXING THE TWO KINDS OF NAME is a client mistake, and half-applying it
    # would leave a part nobody asked for.
    answer = post(url, {"values": {"0.width_mm": 50, "wall_mm": 3}})
    job = answer["job"]
    import time
    for _ in range(200):
        state = get_json("%s/api/job/%s" % (base_url, job))
        if state.get("done"):
            break
        time.sleep(0.25)
    result = state.get("result") or {}
    assert result.get("ok") is False, result
    assert "two different kinds of name" in (result.get("message") or ""), result


def test_a_part_with_no_template_says_so_rather_than_rebuilding_itself(base_url):
    """
    A SLIDER THAT MOVES AND CHANGES NOTHING IS WHAT THIS ROUTE EXISTS TO STOP.

    `params` is validated against a TEMPLATE's parameter model. A level-2 spec
    has no template, so numbers written into it are read by nothing: the part
    rebuilt byte for byte, the route answered ok with an empty list of
    changes, and the library gained a second identical entry.

    Rule 32's third clause is that an instruction which mapped to nothing is
    reported in the words the person used. So it is refused, with a sentence,
    and before the build rather than after it.
    """
    parts = get_json(base_url + "/api/parts")["parts"]
    # NOT AN IMPORT. "No template" is true of somebody else's mesh as well as
    # of a level-2 spec, and an import has no ops to put sliders on - it is
    # triangles. Selecting on that alone picked whichever kind happened to be
    # newest, so this passed or failed depending on what had been imported
    # that afternoon.
    ops_parts = [p for p in parts
                 if p.get("built") is not False
                 and not p.get("template")
                 and p.get("origin") != "imported"]
    if not ops_parts:
        pytest.skip("every built part in the library came from a template")

    answer = post("%s/api/part/%s/params" % (base_url, ops_parts[0]["dir"]),
                  {"values": {"wall_mm": 3.5}})
    job = answer.get("job")
    assert job, "setting a parameter did not start a job"

    import time
    for _ in range(600):
        state = get_json("%s/api/job/%s" % (base_url, job))
        if state.get("done"):
            break
        time.sleep(0.25)
    assert state.get("done"), "the job never finished"

    result = state.get("result") or {}
    assert result.get("ok") is False, (
        "a part with no template accepted a template parameter: %r" % result
    )
    assert "built from operations" in (result.get("message") or ""), result
    # AND IT COST NOTHING. A refusal that builds first has already spent the
    # expensive half and written a part nobody asked for.
    after = get_json(base_url + "/api/parts")["parts"]
    assert len(after) == len(parts), "a refused change still wrote a part"


def test_setting_a_parameter_refuses_nonsense_before_it_builds_anything(base_url):
    """A bad payload is a sentence and a 400, not a job that dies on a thread."""
    built = _first_built(base_url)
    url = "%s/api/part/%s/params" % (base_url, built["dir"])

    assert status_of_post(url, {}) == 400
    assert status_of_post(url, {"values": {}}) == 400
    # A list where a number belongs reaches the template as a type error rather
    # than as a sentence about a dimension.
    assert status_of_post(url, {"values": {"wall_mm": [1, 2]}}) == 400


# ---------------------------------------------------------------------------
# managing the library
# ---------------------------------------------------------------------------


@pytest.fixture
def throwaway(base_url):
    """
    A real part directory made for one test and removed after it.

    NOT one of the library's own. These tests delete things, and a test that
    deletes a part somebody built is a test that costs real work the first time
    it is run on a machine that matters.
    """
    import shutil
    from pathlib import Path as _Path

    directory = _Path("parts") / "zz_test_managed"
    shutil.rmtree(directory, ignore_errors=True)
    (directory / "out").mkdir(parents=True)
    (directory / "spec.yaml").write_text(
        "name: zz_test_managed\nlevel: 1\nmaterial: petg\nnozzle_mm: 0.4\n"
        "layer_mm: 0.2\nprint_axis: z\ntemplate: bracket\nparams: {}\n"
    )
    try:
        yield directory.name
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        shutil.rmtree(directory.with_name("zz_test_renamed"), ignore_errors=True)


# ---------------------------------------------------------------------------
# getting a part onto a printer
# ---------------------------------------------------------------------------


def test_what_is_known_about_printing_a_part_is_measured_not_estimated(base_url):
    """
    WHAT THIS TAB CAN HONESTLY SAY.

    A slicer decides walls, infill and speed, and only then can anybody say
    how long a print takes or what it weighs. whittle does not slice, so a
    time in minutes or a figure in grams here would be a number with nothing
    behind it - rule 29. What it CAN say is most of what you need before
    slicing, and every bit of it is already measured by the time the part
    exists.
    """
    built = _first_built(base_url)
    facts = get_json("%s/api/part/%s/print" % (base_url, built["dir"]))
    assert facts["ready"], facts

    assert len(facts["size_mm"]) == 3
    assert len(facts["bed_mm"]) == 3
    # THE SPARE ROOM IN EACH DIRECTION, because "too big" cannot be acted on
    # and "28 mm too wide" can.
    assert facts["spare_mm"] == [
        round(b - s, 2) for b, s in zip(facts["bed_mm"], facts["size_mm"])
    ]
    assert facts["fits"] is all(v >= 0 for v in facts["spare_mm"])

    # LAYERS IS DIVISION, not a guess.
    assert facts["layers"] == round(facts["size_mm"][2] / facts["layer_mm"])

    # AND NOTHING A SLICER OWNS IS INVENTED.
    for absent in ("minutes", "time_min", "grams", "filament_g", "cost"):
        assert absent not in facts, (
            "%r is a slicer's answer and this does not slice" % absent
        )
    assert "infill" in facts["for_the_slicer"]


def test_an_imported_mesh_can_be_asked_about_printing(base_url):
    """
    IMPORTS ARE THE THING PEOPLE MOST WANT TO PRINT - they downloaded it to
    print it.

    A mesh somebody brought in has no run.json and no regression; it has
    import.json, measured at ingest by the same code. Reading only the first
    two told somebody that the STL they had just imported "has no measured
    size on disk", about a file whose size is in the file beside it.
    """
    imported = [p for p in get_json(base_url + "/api/parts?show=brought-in")["parts"]]
    if not imported:
        pytest.skip("nothing has been brought in on this machine")

    facts = get_json("%s/api/part/%s/print" % (base_url, imported[0]["dir"]))
    assert facts["ready"], facts
    assert len(facts["size_mm"]) == 3
    assert all(v > 0 for v in facts["size_mm"])
    assert facts["layers"] and facts["layers"] > 0
    assert facts["fits"] in (True, False)


def test_a_draft_says_why_there_is_nothing_to_print(base_url):
    """
    A run that never produced a mesh has no size, and the honest answer is a
    sentence rather than an empty panel that looks broken.
    """
    parts = get_json(base_url + "/api/parts?show=unfinished")["parts"]
    if not parts:
        pytest.skip("nothing in this library failed to build")

    facts = get_json("%s/api/part/%s/print" % (base_url, parts[0]["dir"]))
    assert facts["ready"] is False
    assert "no measured size" in facts["why_not"]


def test_every_printer_in_the_catalogue_says_where_its_bed_size_came_from(base_url):
    """
    A MEASURED BED AND A PUBLISHED ONE ARE NOT THE SAME CLAIM.

    This workshop's machine was measured with a tape, which is why its
    height is 255 and not the 260 on the box. Everything else is the
    manufacturer's published maximum, which ignores clips and cable chains.
    A part 2 mm inside one is not the same news as 2 mm inside the other, so
    the distinction has to survive all the way to the screen.
    """
    answer = get_json(base_url + "/api/printers")
    assert len(answer["printers"]) >= 10, "the catalogue is barely a catalogue"

    for machine in answer["printers"]:
        assert machine["source"], "%s says nothing about where it came from" % machine["name"]
        assert len(machine["bed_mm"]) == 3
        assert all(v > 0 for v in machine["bed_mm"])
        assert machine["nozzle_mm"] > 0

    # EXACTLY ONE IS MEASURED, and "not measured here" contains the word
    # "measured" - the first version of this check read every published
    # entry as measured with a tape.
    measured = [m for m in answer["printers"] if m["measured"]]
    assert len(measured) == 1, [m["name"] for m in measured]
    assert "measured" in measured[0]["source"]
    for machine in answer["printers"]:
        if not machine["measured"]:
            assert "not measured" in machine["source"].lower()

    assert answer["using"]["name"]
    assert answer["materials"], "no materials offered"


def test_a_part_can_be_checked_against_a_printer_that_is_not_this_one(base_url):
    """
    Everything whittle verifies is measured against a real machine, and that
    machine was one machine - so anybody else running this was being told
    their part fits a bed they do not own.
    """
    built = _first_built(base_url)
    here = get_json("%s/api/part/%s/print" % (base_url, built["dir"]))

    small = get_json("%s/api/part/%s/print?printer=prusa_mini" % (base_url, built["dir"]))
    assert small["printer"] == "Prusa MINI+"
    assert small["bed_mm"] == [180.0, 180.0, 180.0]
    assert small["size_mm"] == here["size_mm"], "the part changed with the printer"
    assert small["spare_mm"] != here["spare_mm"] or here["bed_mm"] == small["bed_mm"]
    assert "not measured" in small["bed_source"]

    # AN UNKNOWN MACHINE IS REFUSED, never quietly swapped for the default:
    # checking a part against the wrong bed is the failure the catalogue
    # exists to prevent.
    assert status_of(
        "%s/api/part/%s/print?printer=no_such_printer" % (base_url, built["dir"])
    ) == 400


# ---------------------------------------------------------------------------
# bringing in many models at once
# ---------------------------------------------------------------------------


def _one_triangle_stl(name: bytes = b"probe") -> bytes:
    """
    The smallest thing that is honestly a binary STL.

    Written rather than fetched: a test that needs a real model on disk is a
    test that does not run on a fresh checkout.
    """
    import struct

    return (name.ljust(80, b"\0") + struct.pack("<I", 1)
            + struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 10, 0, 0, 10, 10, 0, 0))


def _post_model(base_url, data, filename, tags="", note=""):
    request = urllib.request.Request(
        base_url + "/api/library/model", data=data, method="POST",
        headers={"X-Filename": filename, "X-Tags": tags, "X-Note": note,
                 "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def swept():
    """Whatever a test imported, removed afterwards. The library is real."""
    import shutil
    from pathlib import Path as _Path

    made: list[str] = []
    yield made
    for name in made:
        shutil.rmtree(_Path("library") / name, ignore_errors=True)


def test_a_model_can_be_put_straight_into_the_library(base_url, swept):
    """
    THE DOOR ONTO AN ENGINE THAT ALREADY EXISTED.

    /api/project opens an EDITING SESSION on an upload and files it in a
    temporary directory, because a mesh somebody is editing is not yet a part
    they have decided to keep. That is right for "bring this in and work on
    it" and wrong for "here are two hundred STLs I downloaded" - two hundred
    editing sessions, each holding a mesh, none of them wanted.

    `api.import_stl` has measured, fitted and filed an incoming mesh since it
    was written, and nothing had a route onto it.
    """
    status, answer = _post_model(
        base_url, _one_triangle_stl(), "zz_test_import.stl",
        tags="printables, bracket", note="from a test")
    assert status == 200, answer
    part = answer["part"]
    swept.append(part["name"])

    assert part["origin"] == "imported"
    assert part["source_name"] == "zz_test_import.stl"
    assert part["envelope_mm"] == [10.0, 10.0, 0.0], part
    # TAGS COME FROM THE CLIENT, lowercased and sorted. They are not inferred:
    # a file called knob_v3_final.stl says nothing reliable about where it
    # came from, and a wrong tag on two hundred models is worse than none.
    assert part["tags"] == ["bracket", "printables"]
    assert part["note"] == "from a test"

    # AND IT IS IN THE LIBRARY IMMEDIATELY. The scan caches on what it last
    # saw, so an import that does not turn up until something else happens to
    # invalidate that cache is an import that looks lost.
    listed = get_json(base_url + "/api/parts?show=brought-in")
    assert any(p["name"] == part["name"] for p in listed["parts"]), (
        "an imported model is not in the library it was imported into"
    )

    # THE TAGS BECOME FILTERS, which is what makes a gallery of downloads
    # navigable at all.
    facets = listed["facets"]["tag"]
    assert any(t["name"] == "printables" for t in facets), facets
    tagged = get_json(base_url + "/api/parts?tag=printables")
    assert any(p["name"] == part["name"] for p in tagged["parts"])


def test_a_file_that_is_not_a_model_is_refused_and_nothing_is_kept(base_url):
    """
    A FOLDER OF DOWNLOADS HAS A README IN IT.

    This used to be accepted: the file is named .stl, so it was stored, the
    mesh read failed, and the failure was written down as a "problem" on a
    real library entry. One of those is a curiosity. Two hundred of them is a
    gallery you cannot use, and at a glance they are indistinguishable from
    models that imported properly.

    The refusal is a 400 with a sentence, because a batch importer has to be
    able to tell "skip this one" from "the engine fell over" - and nothing is
    left on disk, or the entry would reappear on the next scan anyway.
    """
    from pathlib import Path as _Path

    before = {d.name for d in _Path("library").iterdir() if d.is_dir()}
    status, answer = _post_model(
        base_url, b"this is a readme, not a model", "zz_readme.stl")

    assert status == 400, answer
    assert "is named like a mesh and is not one" in answer["error"], answer
    assert "Traceback" not in answer["error"]

    after = {d.name for d in _Path("library").iterdir() if d.is_dir()}
    assert after == before, (
        "a refused import left %s behind" % ", ".join(sorted(after - before))
    )


def test_a_tag_that_is_not_a_tag_is_refused_before_anything_is_written(base_url):
    """
    Tags become filter chips. Something that is not a word is not a chip, and
    refusing it on the way in is cheaper than explaining it in the gallery.
    """
    from pathlib import Path as _Path

    before = {d.name for d in _Path("library").iterdir() if d.is_dir()}
    status, answer = _post_model(
        base_url, _one_triangle_stl(), "zz_tagged.stl", tags="fine, <script>")
    assert status == 400, answer
    assert "is not a tag" in answer["error"], answer
    after = {d.name for d in _Path("library").iterdir() if d.is_dir()}
    assert after == before


def test_a_filename_cannot_climb_out_of_the_library(base_url, swept):
    """
    A filename off the wire is where path traversal lives. It is reduced to
    its last component before anything opens it, so the worst a crafted name
    can do is name a directory inside the library.
    """
    from pathlib import Path as _Path

    status, answer = _post_model(
        base_url, _one_triangle_stl(), "../../zz_escaped.stl")
    if status == 200:
        swept.append(answer["part"]["name"])
        landed = _Path(answer["part"]["directory"]).resolve()
        assert _Path("library").resolve() in landed.parents, landed
    else:
        assert status == 400, answer


# ---------------------------------------------------------------------------
# a gallery that works when there are hundreds of models in it
# ---------------------------------------------------------------------------


def test_the_library_route_still_returns_everything_by_default(base_url):
    """
    PAGING IS OPT-IN, AND THIS IS WHY.

    Two clients already read this route and both expect the whole library.
    Making pages the default would quietly turn each of them into an app that
    shows the first sixty models with no hint that there are more - the
    failure being fixed here, reintroduced by the fix.
    """
    answer = get_json(base_url + "/api/parts")
    assert isinstance(answer.get("parts"), list)
    assert answer["total"] == len(answer["parts"]), (
        "asking with no parameters did not return the whole library"
    )
    assert answer["matched"] == answer["total"]
    assert answer["next_cursor"] is None


@pytest.fixture
def a_draft():
    """
    A run that produced nothing, on disk, the way a real one looks.

    Built by hand rather than by failing a generate: this needs the SHAPE of
    a failed run - a handoff and a run record, no spec, no mesh - and
    producing one for real costs three minutes of model time per test.
    """
    import shutil
    from pathlib import Path as _Path

    directory = _Path("parts") / "zz_test_draft"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    (directory / "spec.draft.yaml").write_text(
        "# whittle handoff - the model could not produce a valid spec.\n"
        "name: zz_test_draft\nlevel: 2\n")
    (directory / "run.json").write_text(
        '{"request": "something impossible", "ok": false, "attempts": []}')

    from whittle import library

    library.forget()
    try:
        yield directory.name
    finally:
        shutil.rmtree(directory, ignore_errors=True)
        library.forget()


def test_a_run_that_produced_nothing_is_not_one_of_your_models(base_url, a_draft):
    """
    WHITTLE DOES NOT HALF-BUILD ANYTHING: either a part is there and works,
    or the run failed and said why.

    A failed run used to sit in the gallery among the parts, and a tile
    looks like a part until you open it. `show=models` is what a gallery
    called "your models" leads with - made here or brought in.
    """
    models = get_json(base_url + "/api/parts?show=models")
    assert a_draft not in [p["dir"] for p in models["parts"]], (
        "a run that produced nothing is listed among the models"
    )
    assert all(p["built"] for p in models["parts"])

    # NOT HIDDEN. One tap away, with a count, because a failed run is worth
    # getting back to - it is simply not a model.
    unfinished = get_json(base_url + "/api/parts?show=unfinished")
    assert a_draft in [p["dir"] for p in unfinished["parts"]]
    assert unfinished["facets"]["show"]["unfinished"] >= 1

    # AND THE COUNTS ADD UP. `models` is what the gallery counts; the three
    # kinds together are the whole library.
    counts = models["facets"]["show"]
    assert counts["models"] == counts["made"] + counts["brought-in"]
    assert counts["models"] + counts["unfinished"] == models["total"]


def test_asking_for_everything_still_means_everything(base_url, a_draft):
    """
    `show=models` is the gallery's choice, not a new definition of the
    library. A caller that wants the lot still gets the lot - the CLI and
    the web client both do.
    """
    everything = get_json(base_url + "/api/parts")
    assert a_draft in [p["dir"] for p in everything["parts"]]


def test_the_library_can_be_asked_for_one_page_at_a_time(base_url):
    """
    A thousand downloaded models is the case this exists for: the point of
    that gallery is finding ONE of them, and the whole library crossing the
    wire on every open is what stops it being usable.
    """
    everything = get_json(base_url + "/api/parts")["parts"]
    if len(everything) < 3:
        pytest.skip("not enough parts in this library to page through")

    first = get_json(base_url + "/api/parts?limit=2")
    assert len(first["parts"]) == 2
    assert first["matched"] == len(everything)
    assert first["next_cursor"] == "2"

    second = get_json(base_url + "/api/parts?limit=2&cursor=2")
    assert second["offset"] == 2
    assert [p["dir"] for p in second["parts"]] == [
        p["dir"] for p in everything[2:4]
    ], "the second page is not the next two of the same order"

    # THE PAGES COVER THE LIBRARY, which is the property that matters: a
    # gallery that scrolls must reach the end and must not repeat.
    walked, cursor = [], "0"
    while cursor is not None:
        page = get_json(base_url + "/api/parts?limit=3&cursor=%s" % cursor)
        walked.extend(p["dir"] for p in page["parts"])
        cursor = page["next_cursor"]
    assert walked == [p["dir"] for p in everything], (
        "paging through did not visit every part exactly once"
    )


def test_the_library_is_searched_on_the_engine_side(base_url):
    """
    Searching in the client means shipping the library to the client first.
    The engine already has a search that matches a part's name, template,
    material, the prompt that made it and the file it arrived as - this is
    that search, reachable.
    """
    everything = get_json(base_url + "/api/parts")["parts"]
    if not everything:
        pytest.skip("the library is empty")

    word = everything[0]["name"].split("_")[0]
    found = get_json(base_url + "/api/parts?q=%s" % urllib.parse.quote(word))
    assert found["matched"] <= found["total"]
    assert found["matched"] >= 1, "a part's own name did not find it"
    assert all(word.lower() in json.dumps(p).lower() for p in found["parts"])

    missing = get_json(base_url + "/api/parts?q=zzz_no_such_model_zzz")
    assert missing["matched"] == 0
    assert missing["parts"] == []
    # AND IT STILL SAYS HOW BIG THE LIBRARY IS. "0 of 412" is a search that
    # found nothing; "0" on its own looks like an empty library.
    assert missing["total"] == found["total"]


def test_the_gallery_is_told_how_many_sit_behind_each_filter(base_url):
    """
    A facet is how somebody who has never used this finds out what is in it -
    "brought in (318)" is an offer, where a filter chip that might turn out to
    be empty is a dead end.

    COUNTED OVER THE WHOLE LIBRARY, not the current result, or every filter
    would look like it had emptied the place.
    """
    answer = get_json(base_url + "/api/parts")
    facets = answer["facets"]
    counts = facets["show"]
    # THE THREE KINDS A PART CAN BE, plus `models` - which is a total over
    # two of them rather than a fourth kind, and so is excluded from the
    # sum below. The gallery leads with it: a run that produced nothing is
    # not one of your models.
    kinds = {"made", "brought-in", "unfinished"}
    assert set(counts) == kinds | {"models"}
    assert counts["models"] == counts["made"] + counts["brought-in"]
    assert sum(counts[k] for k in kinds) == answer["total"], (
        "the filters do not add up to the library: %r of %d"
        % (counts, answer["total"])
    )

    for kind, key in (("made", "made"), ("brought-in", "brought-in"),
                      ("unfinished", "unfinished"), ("models", "models")):
        page = get_json(base_url + "/api/parts?show=%s" % kind)
        assert page["matched"] == counts[key], (
            "%s says %d and returns %d" % (kind, counts[key], page["matched"])
        )

    # Unchanged whichever way it is filtered, because it describes the library.
    narrowed = get_json(base_url + "/api/parts?show=made")["facets"]["show"]
    assert narrowed == counts


def test_one_tile_per_thing_rather_than_one_per_build(base_url):
    """
    FOUR IDENTICAL TILES ARE FOUR CHANCES TO OPEN THE WRONG ONE.

    A refine writes a NEW part and leaves the old one alone - that is what
    makes editing safe - so "a birdhouse", the taller one and the one with
    3.5 mm walls are three directories all called "birdhouse".

    COLLAPSED ON THE ENGINE, because the client holds a page rather than the
    library: a chain whose members straddle a page boundary would collapse
    differently depending on where the page fell.
    """
    latest = get_json(base_url + "/api/parts")
    every = get_json(base_url + "/api/parts?builds=all")

    assert every["total"] >= latest["total"]
    if every["total"] == latest["total"]:
        pytest.skip("no part in this library has been built more than once")

    chains = [p for p in latest["parts"] if p.get("builds", 1) > 1]
    assert chains, "the library has chains and none of them was collapsed"

    # THE COUNT IS THE WHOLE CHAIN. Without it a collapsed chain looks like
    # the only build there ever was.
    total_builds = sum(p.get("builds", 1) for p in latest["parts"])
    assert total_builds == every["total"], (
        "the collapsed counts (%d) do not add up to every build (%d)"
        % (total_builds, every["total"])
    )

    # AND THE SURVIVOR IS THE LATEST, not whichever came first in the scan.
    for part in chains:
        import re as _re

        family = [p for p in every["parts"]
                  if p["name"] == part["name"]
                  and _re.sub(r"_\d+$", "", p["dir"]) == _re.sub(r"_\d+$", "", part["dir"])]
        newest = max(family, key=lambda p: int(
            (_re.search(r"_(\d+)$", p["dir"]) or _re.match(r"(1)", "1")).group(1)))
        assert part["dir"] == newest["dir"], (
            "%s stands for the chain but %s is the later build"
            % (part["dir"], newest["dir"])
        )


def test_a_collapsed_count_never_leaks_onto_another_request(base_url):
    """
    THE CACHE HANDS OUT THE SAME OBJECTS.

    The library scan caches LibraryEntry objects and gives the same ones to
    every request, so writing a chain count onto an entry would leave it
    there - and the next `?builds=all`, which collapses nothing, would report
    a chain of twenty on a part standing only for itself. Counts travel
    beside the entries, never on them.
    """
    get_json(base_url + "/api/parts")                    # collapse, stamping
    every = get_json(base_url + "/api/parts?builds=all")  # must be untouched
    stamped = [p["dir"] for p in every["parts"] if p.get("builds", 1) != 1]
    assert not stamped, (
        "asking for every build reported chain counts on %s" % ", ".join(stamped)
    )


def test_a_sort_nobody_implemented_falls_back_rather_than_failing(base_url):
    """
    Query strings come from URLs people can type. An unknown sort is newest,
    a cursor that is not a number is the start - a gallery must not 500
    because somebody edited the address bar.
    """
    newest = get_json(base_url + "/api/parts")["parts"]
    odd = get_json(base_url + "/api/parts?sort=sideways&cursor=banana&limit=x")
    assert odd["sort"] == "newest"
    assert odd["offset"] == 0
    assert [p["dir"] for p in odd["parts"]] == [p["dir"] for p in newest]

    by_name = get_json(base_url + "/api/parts?sort=name")["parts"]
    assert [p["name"] for p in by_name] == sorted(
        (p["name"] for p in by_name), key=str.lower)


def test_looking_at_a_part_does_not_write_a_new_one(base_url):
    """
    THE LIBRARY FILLED UP WITH PARTS NOBODY MADE.

    The viewer shows a part ASSEMBLED, not as it prints - a birdhouse rather
    than a box with a slab beside it - and getting that means rebuilding the
    spec, because the STL on disk is the print layout. The rebuild was called
    with `out_dir=None`, which is `api.build`'s "pick me a free directory
    under parts/" - correct for a build somebody asked for, and completely
    wrong for one nobody did.

    So turning a part around on screen wrote a new directory holding one
    `out/<name>.stl` and nothing else: no spec, no report, no run.json. The
    library scans directories, so each appeared as a built part that cannot be
    rebuilt. `pot_cylinder`, `enclosure_9ba7a3`, `wall_bracket_70cc2c` - a
    dozen of them, every one somebody looking at something.

    Counted rather than named, because the fault is "a directory appeared",
    and which name it would have taken depends on what is already there.
    """
    from pathlib import Path as _Path

    parts = _Path("parts")
    if not parts.is_dir():
        pytest.skip("no parts directory in this checkout")

    listed = get_json(base_url + "/api/parts")["parts"]
    built = [p for p in listed if p.get("built") is not False]
    if not built:
        pytest.skip("the library has no built part to look at")

    before = {d.name for d in parts.iterdir() if d.is_dir()}
    # THE ASSEMBLED FORM, which is the request that rebuilt the spec.
    status_of("%s/api/part/%s/glb" % (base_url, built[0]["dir"]))
    after = {d.name for d in parts.iterdir() if d.is_dir()}

    assert after == before, (
        "looking at a part added %s to the library"
        % ", ".join(sorted(after - before))
    )


def test_a_directory_name_wins_over_another_part_that_answers_to_it(base_url):
    """
    THIS DELETED A BUILT PART.

    A part's spec name and its directory name are different things, and both
    are used: every edit keeps the spec name, so `parts/a_hinge` holds a spec
    called "hinge" and exports `hinge.stl`. Set a number on it and the rebuild
    lands in `parts/hinge` - a directory whose name really is "hinge".

    The resolver accepted either name in one pass, so whichever entry came
    first answered: asking for "hinge" returned `parts/a_hinge`. Reading a
    part that way shows somebody the unchanged original they just asked to
    change. Deleting one that way removed parts/a_hinge while the caller was
    tidying up the copy it had just made - which is exactly what happened,
    to a part that had taken twenty minutes of model time to get right.

    So: a directory answers for its own name, always, and a spec-name match
    is only consulted when no directory does.
    """
    import shutil
    from pathlib import Path as _Path

    # TWO REAL DIRECTORIES, ONE NAME BETWEEN THEM. Built by hand rather than
    # generated: the shape of the trap is two directories where one's NAME is
    # the other's spec, and that is three files, not a build.
    spec = ("name: zz_twin\nlevel: 1\nmaterial: petg\nnozzle_mm: 0.4\n"
            "layer_mm: 0.2\nprint_axis: z\ntemplate: bracket\nparams: {}\n")
    long_way = _Path("parts") / "zz_named_zz_twin"
    short_way = _Path("parts") / "zz_twin"
    for directory in (long_way, short_way):
        shutil.rmtree(directory, ignore_errors=True)
        (directory / "out").mkdir(parents=True)
        (directory / "spec.yaml").write_text(spec)
    # The STL is named after the SPEC, which is what made the long way answer
    # to the short way's name.
    (long_way / "out" / "zz_twin.stl").write_bytes(b"solid x\nendsolid x\n")
    (short_way / "out" / "zz_twin.stl").write_bytes(b"solid x\nendsolid x\n")

    try:
        from whittle.web.server import _resolve_part

        found, _stl = _resolve_part("zz_twin")
        assert found.name == "zz_twin", (
            "asking for %r returned %s - a route that deletes would have "
            "removed the wrong part" % ("zz_twin", found)
        )

        # AND THE OTHER NAME STILL WORKS, which is the whole reason the
        # fallback exists: a part linked by its spec name must still resolve.
        found, _stl = _resolve_part("zz_named_zz_twin")
        assert found.name == "zz_named_zz_twin", found

        # END TO END, because the resolver is only interesting through a route.
        deleted = post("%s/api/part/zz_twin/delete" % base_url, {})
        assert deleted.get("ok") or deleted.get("removed"), deleted
        assert not short_way.exists(), "the addressed part was not removed"
        assert long_way.exists(), (
            "deleting zz_twin removed zz_named_zz_twin, which is the bug this "
            "test is named after"
        )
    finally:
        shutil.rmtree(long_way, ignore_errors=True)
        shutil.rmtree(short_way, ignore_errors=True)


def test_a_part_can_be_renamed_and_deleted(base_url, throwaway):


    """
    A library you cannot remove anything from fills with failed attempts until
    finding the good one is the hard part - and on a CPU-only engine most of
    what accumulates is drafts from runs that timed out.
    """
    renamed = post("%s/api/part/%s/rename" % (base_url, throwaway),
                   {"name": "zz_test_renamed"})
    assert renamed["ok"] and renamed["dir"] == "zz_test_renamed"
    assert status_of("%s/api/part/zz_test_renamed" % base_url) == 200

    # THE OLD NAME STILL RESOLVES, AND THAT IS THE DESIGN. A part answers to
    # both its directory and its spec's own name - `_resolve_part` says so at
    # length, because both get shown to people and both get linked. A rename
    # changes the directory and deliberately leaves the spec alone, so the
    # spec's name goes on working. What must be true is that it now points at
    # the NEW directory rather than at nothing.
    still = get_json("%s/api/part/%s" % (base_url, throwaway))
    assert still["dir"] == "zz_test_renamed", (
        "the spec name resolves to %r, not to the renamed directory"
        % still["dir"]
    )

    gone = post("%s/api/part/zz_test_renamed/delete" % base_url, {})
    assert gone["ok"]
    assert gone["files"] >= 1, "it reported removing nothing"
    assert status_of("%s/api/part/zz_test_renamed" % base_url) == 404


def test_nothing_outside_the_managed_roots_can_be_deleted(base_url):
    """
    THE GUARD IS THE SERVER'S, NOT THE CLIENT'S.

    A confirmation dialogue is a courtesy. What makes a route that removes a
    directory tree safe is that a crafted name cannot reach outside parts/ or
    library/ - so every shape of escape is refused rather than sanitised,
    because sanitising is where path traversal bugs live.
    """
    for name in ("..", "../..", "..%2F..%2Fetc", "/etc", "not_a_real_part"):
        code = status_of_post("%s/api/part/%s/delete" % (base_url, name), {})
        assert code in (400, 404), (
            "%r answered %s to a delete - it must be refused" % (name, code)
        )


def test_a_rename_will_not_take_a_name_that_is_not_one(base_url, throwaway):
    """A new name reaches the filesystem, so it is checked as hard as the old."""
    for wanted in ("../escape", "with/slash", "", "  "):
        code = status_of_post(
            "%s/api/part/%s/rename" % (base_url, throwaway), {"name": wanted})
        assert code == 400, "%r was accepted as a directory name" % wanted


def test_a_rename_will_not_overwrite_something_that_is_there(base_url, throwaway):
    """Renaming onto an existing part would silently merge two directories."""
    existing = _first_built(base_url)["dir"]
    code = status_of_post(
        "%s/api/part/%s/rename" % (base_url, throwaway), {"name": existing})
    assert code == 409, "a rename over %r answered %s" % (existing, code)


def test_refining_a_part_that_is_not_there_says_so(base_url):
    """A missing part is a sentence, not a traceback."""
    answer = post("%s/api/refine" % base_url,
                  {"name": "not_a_part", "instruction": "make it taller"})
    job = answer.get("job")
    assert job, "the route refused before it could even look"

    import time
    for _ in range(20):
        state = get_json("%s/api/job/%s" % (base_url, job))
        if state.get("done"):
            result = state.get("result") or {}
            assert result.get("ok") is False
            assert "no part called" in str(result.get("message", ""))
            return
        time.sleep(0.25)
    raise AssertionError("the job never finished")


def test_the_template_schema_carries_real_bounds_for_the_sliders(base_url):
    """
    THIS IS WHERE THE SLIDERS' MIN AND MAX COME FROM, and the reason the route
    exists rather than the clients holding a table. The bounds are the
    Pydantic schema's own, so a slider cannot offer a value the builder will
    reject - and a client inventing its own range would be guessing at a
    dimension, which is the one thing this project does not do.
    """
    schema = get_json("%s/api/template/louvre_vent" % base_url)
    params = {p["name"]: p for p in schema["params"]}

    frame = params["frame_w_mm"]
    assert frame["units"] == "mm"
    assert frame["bounds"]["gt"] == 10.0
    assert frame["bounds"]["le"] == 400.0
    assert frame["description"]

    # An INTEGER parameter is typed as one, which is what stops a blade count
    # rendering as "4.0" and sliding to 4.3.
    assert params["n_blades"]["type"] == "int"
    assert params["n_blades"]["bounds"] == {"ge": 2, "le": 24}


def test_every_template_the_health_lists_can_be_read(base_url):
    """
    The workspace builds its parameter form from whatever the registry knows,
    with no per-template code. A template that is listed but cannot be
    described is a panel that fails to open for exactly one part.
    """
    for name in get_json("%s/api/health" % base_url)["templates"]:
        schema = get_json("%s/api/template/%s" % (base_url, name))
        assert schema["name"] == name
        assert isinstance(schema.get("params"), list)


def test_an_unknown_template_is_a_404_and_not_a_500(base_url):
    assert status_of("%s/api/template/not_a_template" % base_url) == 404


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "../../etc/passwd",
    "..%2f..%2fetc",
    "name with spaces",
    "",
    "x" * 200,
])
def test_a_part_name_that_is_not_a_plain_name_is_refused(base_url, name):
    """
    Part names reach the filesystem. Anything that is not a plain name is
    refused outright rather than sanitised - sanitising is where traversal
    bugs live.
    """
    code = status_of("%s/api/part/%s/stl" % (base_url, urllib.parse.quote(name)))
    assert code in (400, 404), "got %d for %r" % (code, name)


def test_static_files_cannot_escape_their_directory(base_url):
    for path in ("/static/../server.py", "/static/..%2fserver.py",
                 "/static/../../config/default.toml"):
        assert status_of(base_url + path) in (400, 404), "escaped with %r" % path


def test_an_unknown_route_is_a_404_not_a_crash(base_url):
    assert status_of(base_url + "/api/nonsense") == 404


def test_generating_with_no_request_is_refused(base_url):
    request = urllib.request.Request(
        base_url + "/api/generate",
        data=json.dumps({"request": "   "}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=30)
    assert exc.value.code == 400


def test_a_body_that_is_not_json_is_refused_with_a_readable_message(base_url):
    request = urllib.request.Request(
        base_url + "/api/generate",
        data=b"{not json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=30)
    assert exc.value.code == 400
    assert "JSON" in json.loads(exc.value.read())["error"]


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


def test_a_job_replays_everything_that_happened_before_you_connected(base_url):
    """
    A phone that locks its screen drops the SSE connection. When it comes back
    it needs the whole story, not only what happened after it reconnected.
    """
    done = threading.Event()

    def work(job):
        job.emit("note", text="first")
        job.emit("note", text="second")
        done.wait(5)
        return {"ok": True, "name": "nothing"}

    job = web._start_job("test", "a test", work)
    while len(job.events) < 3:                    # started + two notes
        pass
    backlog, queue_ = job.subscribe()
    try:
        texts = [e.get("text") for e in backlog if e["kind"] == "note"]
        assert texts == ["first", "second"], (
            "a client connecting late got %r instead of the whole log" % texts
        )
    finally:
        job.unsubscribe(queue_)
        done.set()


def test_a_job_that_raises_reports_a_readable_message_not_a_traceback(base_url):
    done = threading.Event()

    def work(job):
        raise RuntimeError("the wall is 0.1 mm and the nozzle is 0.4 mm")

    job = web._start_job("test", "a test", work)
    for _ in range(200):
        if job.done:
            break
        done.wait(0.05)
    assert job.done
    assert job.result["ok"] is False
    assert "nozzle" in job.result["message"]
    assert "Traceback" not in job.result["message"]


def test_asking_for_a_job_that_does_not_exist_is_a_404(base_url):
    assert status_of(base_url + "/api/job/deadbeef0000") == 404


def test_the_machine_says_what_it_is_working_on(base_url):
    """
    "YOU CAN LEAVE IT RUNNING" HAS TO BE CHECKABLE.

    Both clients promise that a build outlives the screen that started it,
    and until /api/jobs there was no way to ask what became of one. A phone
    that locked mid-build had to guess from whether a part turned up later.
    """
    release = threading.Event()

    def work(job):
        job.emit("note", text="building geometry")
        release.wait(5)
        return {"ok": True, "name": "a-part"}

    job = web._start_job("generate", "a bracket for an 8 mm rod", work)
    while len(job.events) < 2:                    # started + the note
        pass

    rows = get_json(base_url + "/api/jobs")["jobs"]
    mine = [row for row in rows if row["id"] == job.id]
    assert mine, "the running job was not in %r" % rows
    row = mine[0]
    assert row["done"] is False
    assert row["kind"] == "generate"
    assert row["request"] == "a bracket for an 8 mm rod"
    # THE ENGINE'S LAST WORDS, not a stage this endpoint decided it must be at.
    assert row["note"] == "building geometry"
    assert row["elapsed_s"] >= 0

    release.set()
    for _ in range(200):
        if job.done:
            break
        time.sleep(0.05)

    row = [r for r in get_json(base_url + "/api/jobs")["jobs"]
           if r["id"] == job.id][0]
    assert row["done"] is True
    assert row["ok"] is True
    assert row["name"] == "a-part"


def test_a_finished_job_stops_its_clock_rather_than_ageing(base_url):
    """
    A done job measured against `now` reads as hours long by the evening.
    That is a wrong number on a screen whose whole claim is measured numbers,
    not a stale one - so the clock stops at the last event.
    """

    def work(job):
        return {"ok": True, "name": "quick"}

    job = web._start_job("generate", "something quick", work)
    for _ in range(200):
        if job.done:
            break
        time.sleep(0.05)

    first = [r for r in get_json(base_url + "/api/jobs")["jobs"]
             if r["id"] == job.id][0]["elapsed_s"]
    time.sleep(0.4)
    second = [r for r in get_json(base_url + "/api/jobs")["jobs"]
              if r["id"] == job.id][0]["elapsed_s"]
    assert first == second, (
        "a finished job aged from %.1fs to %.1fs between two reads" % (first, second)
    )


# ---------------------------------------------------------------------------
# one UI, and it has to be installable on a phone
# ---------------------------------------------------------------------------


def test_the_desktop_entry_point_reaches_the_web_ui():
    """
    THE BUG THAT WASTED A SESSION, PINNED.

    A console script shim records the import path it was generated with. An
    editable install updates the modules and NOT the shim, so repointing
    `whittle-gui` in pyproject.toml changes nothing until somebody reinstalls -
    and the symptom is launching the old interface and concluding the work was
    never done. Both paths must land on the shell.
    """
    # READ THE SOURCE, DO NOT IMPORT IT. whittle.gui.app pulls in PySide6 at
    # module scope, and importing Qt inside a pytest process that is already
    # running an HTTP server hangs indefinitely - the test suite stopped dead
    # at this point with no output. The fact under test is textual anyway.
    from pathlib import Path

    src = Path("whittle/gui/app.py").read_text()
    assert "def classic_main(" in src, "--classic has nothing to reach"
    forward = src[src.index("def main("):]
    assert "shell_main" in forward, (
        "whittle.gui.app.main no longer forwards to the shell, so a stale "
        "console script shim will launch the old Qt app"
    )


def test_the_shell_serves_the_same_files_the_phone_gets():
    """One UI means one set of files, not a desktop port of them."""
    from pathlib import Path

    from whittle.web import server as web_server

    # Same reason as above: gui.shell is read, not imported.
    src = Path("whittle/gui/shell.py").read_text()
    assert "from whittle.web.server import Handler" in src, (
        "the desktop shell no longer serves the web app's own handler, so the "
        "two front ends can diverge again"
    )
    assert web_server.STATIC_DIR.is_dir()
    for name in ("index.html", "app.css", "app.js"):
        assert (web_server.STATIC_DIR / name).is_file()


def test_the_manifest_is_served_as_a_manifest(base_url):
    """
    Served as application/octet-stream a manifest is ignored by every browser,
    silently, and the app simply is not installable with nothing to say why.
    """
    with get(base_url + "/static/manifest.webmanifest") as response:
        assert response.headers.get("Content-Type") == "application/manifest+json"
        manifest = json.loads(response.read())
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes, "Android needs 192 and 512"
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"]), (
        "without a maskable icon Android crops the mark inside a white circle"
    )


def test_every_icon_the_manifest_promises_exists(base_url):
    manifest = get_json(base_url + "/static/manifest.webmanifest")
    for icon in manifest["icons"]:
        assert status_of(base_url + icon["src"]) == 200, "missing %s" % icon["src"]
    assert status_of(base_url + "/static/icons/apple-touch-icon.png") == 200


def test_the_service_worker_may_control_the_whole_app(base_url):
    """
    A worker served from /static/ can only control /static/ unless the response
    says otherwise. Without the header it registers, reports success, and
    controls nothing.
    """
    with get(base_url + "/static/sw.js") as response:
        assert response.headers.get("Service-Worker-Allowed") == "/"
        assert response.headers.get("Content-Type") == "text/javascript"
        body = response.read().decode()
    assert "/api/" in body, "the worker does not mention the API at all"


def test_the_service_worker_never_caches_the_api(base_url):
    """
    A cached /api/parts is a library missing what you made this morning, and a
    cached STL is somebody printing yesterday's geometry. The whole claim of
    this program is that the numbers shown are the numbers measured.
    """
    with get(base_url + "/static/sw.js") as response:
        body = response.read().decode()

    # Check the GUARD, not the prose. The first "/api/" in the file is in the
    # explanatory comment at the top, so searching for the first occurrence and
    # looking nearby for "return" was reading documentation and calling it a
    # test - it failed while the actual guard was right there and correct.
    assert "if (url.pathname.startsWith('/api/')) return;" in body, (
        "the service worker does not bail out of /api/ before its caching "
        "logic, so a part list or an STL can be served stale"
    )
    fetch_body = body[body.index("addEventListener('fetch'"):]
    assert fetch_body.index("startsWith('/api/')") < fetch_body.index("respondWith"), (
        "the /api/ guard comes AFTER respondWith, so it does not guard anything"
    )


def test_the_page_declares_itself_installable(base_url):
    with get(base_url + "/") as response:
        html = response.read().decode()
    for tag in ('rel="manifest"',
                'apple-mobile-web-app-capable',
                'apple-touch-icon'):
        assert tag in html, "missing %s - iOS will not install it" % tag


# ---------------------------------------------------------------------------
# saying what the machine can do, honestly
# ---------------------------------------------------------------------------


def test_health_says_what_this_machine_can_do(base_url):
    data = get_json(base_url + "/api/health")
    cap = data.get("capability")
    assert cap, "health does not report capability at all"
    assert cap["tier"] in ("gpu", "cpu", "no-model", "unknown")
    assert cap["headline"], "no headline for a person to read"


def test_no_gpu_is_reported_as_slow_and_never_as_broken():
    """
    A machine with no GPU is not unsupported. Every template, every fitter,
    every import and every export works identically on it - only the prompt
    step is slow. Telling somebody their working machine is broken is worse
    than telling them nothing.
    """
    from whittle.capability import Capability

    cap = Capability(gpu=False, model_available=True, model_name="qwen2.5-coder:7b")
    headline = cap.headline().lower()
    assert "cpu" in headline
    assert "minute" in headline, "the wait is not stated, so it reads as a hang"
    for word in ("unsupported", "error", "failed", "cannot", "required"):
        assert word not in headline, "%r makes a working machine sound broken" % word


def test_the_wait_is_stated_before_it_is_endured():
    from whittle.capability import Capability

    cpu = Capability(gpu=False, model_available=True, model_name="m")
    gpu = Capability(gpu=True, model_on_gpu=True, model_available=True, model_name="m")
    assert cpu.prompt_seconds > gpu.prompt_seconds * 3, (
        "if CPU and GPU are quoted the same, the number is decorative"
    )
    assert str(round(cpu.prompt_seconds / 60)) in cpu.headline()


def test_no_model_still_offers_the_rest_of_the_program():
    """
    `spec.yaml` is the durable artifact and none of it needs a model. The
    message has to say so, or somebody with no Ollama concludes the app is
    useless to them.
    """
    from whittle.capability import Capability

    cap = Capability(model_available=False)
    assert cap.tier == "no-model"
    text = cap.headline().lower()
    assert "rebuild" in text or "works" in text


def test_requiring_a_gpu_explains_what_still_works():
    """
    A refusal that only says "GPU required" leaves somebody thinking the whole
    program needs one. It does not - almost none of it does.
    """
    import pytest as _pytest

    from whittle.capability import Capability, require_gpu

    with _pytest.raises(RuntimeError) as exc:
        require_gpu("Generating a mesh", Capability(gpu=False))
    message = str(exc.value)
    assert "Everything else" in message
    assert "export" in message

    # And it must not refuse on a machine that HAS one.
    require_gpu("Generating a mesh", Capability(gpu=True))


def test_nothing_in_the_program_currently_requires_a_gpu():
    """
    A slow answer is an answer. If require_gpu ever gets called on a path that
    merely runs slowly, a working program disappears for everyone without a
    graphics card.
    """
    import subprocess

    out = subprocess.run(
        ["grep", "-rn", "require_gpu", "whittle/"],
        capture_output=True, text=True,
    )
    callers = [line for line in out.stdout.splitlines()
               if "capability.py" not in line]
    assert not callers, "require_gpu is called from: %s" % callers
