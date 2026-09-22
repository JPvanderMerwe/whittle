"""
whittle over HTTP: the same program, reachable from a browser and a phone.

WHY STDLIB AND NOT A FRAMEWORK
-------------------------------
FastAPI is installed here and there is no ASGI server to run it on, and adding
one to reach the eight routes below would be a dependency bought for nothing.
`ThreadingHTTPServer` serves them, streams progress over Server-Sent Events,
and has no install step on any machine this ever runs on - which matters more
than usual, because the point of this layer is to be reachable from a phone
that has no Python on it at all.

WHY THE 3D VIEW IS PICTURES AND NOT WEBGL
------------------------------------------
The obvious thing is three.js and a mesh in the browser. That means either a
CDN - which does not work offline and is a third-party dependency in a program
whose whole argument is that it has none - or vendoring a megabyte of
someone else's JavaScript. And it means every phone that opens this has to be
able to run WebGL well enough to shade a 40 000-triangle mesh.

There is already a renderer. It is the CPU z-buffer rasteriser that draws every
other picture this program produces, it is verified against a deliberately
asymmetric part, and it runs on the machine that already has the geometry
loaded. So the viewer asks it for the part at a series of angles and lets you
drag between them. It is a turntable, not a free camera - you cannot fly around
it - but it works identically on a ten-year-old phone and a workstation, it
needs no JavaScript library at all, and what you see is the same rasteriser
that draws the height maps, so the two cannot disagree.

RUNNING WORK IS NOT KEPT IN THE REQUEST
----------------------------------------
A generation takes a minute or two on this hardware. Doing it inside the POST
means a phone that locks its screen loses the part. So a POST starts a job,
returns its id immediately, and the browser follows it on a separate SSE
stream that it can drop and reopen without the work noticing.
"""

from __future__ import annotations

import json
import mimetypes
import queue
import re
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

STATIC_DIR = Path(__file__).parent / "static"

# mimetypes does not know these, and a manifest served as
# application/octet-stream is ignored by every browser - silently, so the app
# simply is not installable and nothing says why.
EXTRA_TYPES = {
    ".webmanifest": "application/manifest+json",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
}

# How many angles the turntable has. 24 is 15 degrees apart, which reads as
# continuous when you drag it and is cheap enough to render on demand.
TURNTABLE_STEPS = 24

#: What a request is built in when nobody says.
#:
#: WRITTEN ONCE, AND PUBLISHED. It was spelled "petg" inline in two handlers,
#: and no client could read it - so the phone picked the first name off the
#: material list instead, which is sorted. The day the shop's full stock went
#: into the config that list started "asa", and the app silently began offering
#: to print everything in ASA while the server still built in PETG. Two
#: different answers to "what will this be made of", neither of them chosen by
#: anybody.
#:
#: It goes out on /api/health so a client names the same material the server
#: will actually use.
DEFAULT_MATERIAL = "petg"

# RENDER VERSION, AND WHY AN IMMUTABLE CACHE NEEDS ONE.
#
# Frames are served `immutable, max-age=604800` because a built part's geometry
# never changes - a refinement writes a new part. That is true of the GEOMETRY
# and not of the PICTURE. Changing the renderer changes every frame's content
# without changing any frame's URL, so every browser that has been here keeps
# showing the old ones for a week and no amount of reloading helps.
#
# It bit immediately: the renderer went from opaque RGB to transparent RGBA and
# the page kept drawing the old flat-backed frames, which was the exact
# rectangle-around-the-part the change was meant to remove.
#
# BUMP THIS whenever the renderer's output changes - background, alpha,
# shading, camera, size. The client appends it to every frame URL.
# 2 -> 3: the turntable renders in the design's technical style - `bezel`
# faces, drawn feature edges, a graticule and three axis lines - instead of a
# shaded grey Lambert render. Every frame's content changed and no frame's URL
# would have, which is exactly what this constant is for.
RENDER_VERSION = 3

# Renders are cached by (part, step, size) and never invalidated, because a
# built part's geometry does not change - a refinement writes a NEW part.
_RENDER_CACHE: dict[tuple, bytes] = {}

# MESH VERSION, for the same reason RENDER_VERSION exists, one layer down.
#
# The GLB was first served as `immutable, max-age=604800` on the argument that
# it is the MESH and not a picture of it, so the renderer's choices could not
# affect it. That argument was wrong the moment the part's grey was baked into
# the file: the GLB carries a material as well as triangles, and a viewer that
# had already fetched the colourless one kept drawing a white silhouette for a
# week with no way to ask for the new file - which is the identical bug the
# frames hit, in the identical week-long cache.
#
# BUMP THIS whenever the GLB's CONTENT changes for an unchanged part: baked
# colour, export options, units, orientation. Clients append it to the URL, so
# a bump is a new URL and the hard cache stays correct instead of stale.
#
# 1 -> 2: the part's own grey baked in as face colours.
MESH_VERSION = 2

# GLB, for the front ends that render on their own GPU rather than being sent
# pictures. Cached by part for the same reason the frames are: a built part's
# geometry does not change, a refinement writes a NEW part. The conversion is
# a mesh walk and costs real time on a 40 000-face bowl.
_GLB_CACHE: dict[str, bytes] = {}
_RENDER_LOCK = threading.Lock()

SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


class HttpError(Exception):
    """A response the client should see, with its status code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """
    One generation or refinement, running on its own thread.

    `events` is a list and not just a queue on purpose: a phone that locks its
    screen drops the SSE connection, and when it comes back it needs the whole
    story so far, not only what happened after it reconnected.
    """

    id: str
    kind: str
    request: str
    events: list[dict] = field(default_factory=list)
    subscribers: list[queue.Queue] = field(default_factory=list)
    done: bool = False
    result: dict | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, kind: str, **payload) -> None:
        event = {"kind": kind, "at": round(time.time(), 3), **payload}
        with self.lock:
            self.events.append(event)
            subscribers = list(self.subscribers)
        for q in subscribers:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def subscribe(self) -> tuple[list[dict], queue.Queue]:
        q: queue.Queue = queue.Queue(maxsize=512)
        with self.lock:
            backlog = list(self.events)
            self.subscribers.append(q)
        return backlog, q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


def _start_job(kind: str, request: str, work) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, request=request)
    with JOBS_LOCK:
        JOBS[job.id] = job

    def run():
        try:
            job.emit("started", request=request)
            result = work(job)
            job.result = result
            job.emit("done", **result)
        except Exception as exc:
            # The message a person can act on, not the traceback. The traceback
            # goes to the console where whoever is running the server can see it.
            traceback.print_exc()
            job.result = {"ok": False, "message": str(exc).split("\n")[0][:400]}
            job.emit("failed", message=job.result["message"])
        finally:
            job.done = True
            job.emit("closed")

    threading.Thread(target=run, daemon=True, name="job-%s" % job.id).start()
    return job


# ---------------------------------------------------------------------------
# the work itself
# ---------------------------------------------------------------------------


def _assumptions_payload(part) -> list[dict]:
    """
    The numbers that were chosen rather than given, named.

    ONE READER FOR BOTH ROUTES. A part that has just been built has its
    BuildResult in memory; a part opened from the library a week later has only
    what was written to disk. Both show the same panel, so both come through
    here - and the stored copy is preferred to nothing rather than the panel
    quietly emptying the moment the build result goes out of scope.
    """
    found = list(getattr(getattr(part, "build", None), "assumptions", None) or [])
    if not found:
        return []
    return [
        {
            "name": str(getattr(a, "name", "")),
            "value": getattr(a, "value", None),
            "units": str(getattr(a, "units", "") or ""),
            "why": str(getattr(a, "why", "") or ""),
        }
        for a in found
    ]


def _stored_assumptions(part_dir: Path) -> list[dict]:
    """
    The same list, off disk, for a part nobody has just built.

    THE LIBRARY IS THE ONLY WAY ANYBODY EVER SEES A PART AGAIN, and rule 14's
    marked parameters were reachable for about as long as one screen stayed
    open. run.json records the build, so they were on disk the whole time.

    Returns [] rather than None for a part that assumed nothing - which is a
    real answer and a different one from a part built before this was recorded.
    """
    run = part_dir / "run.json"
    if not run.is_file():
        return []
    try:
        data = json.loads(run.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    found = data.get("assumptions")
    if not isinstance(found, list):
        return []
    out = []
    for item in found:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        out.append({
            "name": str(item.get("name", "")),
            "value": item.get("value"),
            "units": str(item.get("units") or ""),
            "why": str(item.get("why") or ""),
        })
    return out


def _part_payload(part) -> dict:
    """Everything the browser needs about one built part, and nothing heavy."""
    report = part.report
    spec = part.spec
    mesh = getattr(report, "mesh", None)
    size = None
    if mesh is not None and getattr(mesh, "bbox_mm", None):
        size = [round(float(v), 1) for v in mesh.bbox_mm]

    return {
        "name": part.name,
        # THE DIRECTORY, WHICH IS THE PART'S REAL IDENTITY.
        #
        # `name` comes from the spec, and a refinement keeps the spec's name -
        # so refining "birdhouse" writes parts/birdhouse_2 and reports itself
        # as "birdhouse". The client then opened /api/part/birdhouse, got the
        # ORIGINAL back, and showed somebody the unchanged part they had just
        # asked to change. It looked exactly like the change had done nothing.
        #
        # Every route resolves a part by a name that may be either; the
        # directory is the one that is unique. Clients navigate by this.
        "dir": Path(part.part_dir).name,
        "verdict": report.verdict,
        "ok": bool(report.ok),
        "size_mm": size,
        "volume_cm3": round(float(getattr(mesh, "volume_mm3", 0.0)) / 1000.0, 1)
        if mesh is not None else None,
        "bodies": int(getattr(mesh, "body_count", 0)) if mesh is not None else None,
        "watertight": bool(getattr(mesh, "watertight", False)) if mesh is not None else None,
        "level": getattr(spec, "level", None),
        "template": getattr(spec, "template", None),
        "material": getattr(spec, "material", None),
        "problems": [str(p) for p in getattr(report, "problems", [])],
        "warnings": [str(w) for w in getattr(report, "warnings", [])],
        "notes": [str(n) for n in getattr(report, "notes", [])],
        # ASSUMPTIONS, FROM THE BUILD - WHICH IS WHERE THEY LIVE.
        #
        # This read `getattr(report, "assumptions", [])`, and `report` is the
        # VerifyReport, which has no such field and never has. The getattr
        # default swallowed it, so the list was ALWAYS EMPTY: every client has
        # been drawing an assumptions panel that could not render, since the
        # route was written. They are on `part.build`, the BuildResult, which
        # is what the template returns them on.
        #
        # And as DATA rather than str(). An Assumption is a Pydantic model, so
        # even once the list was populated, `str(a)` would have put this on a
        # phone screen:
        #
        #   name='corner_r_mm' value=6.0 units='mm' why='Not stated, so it ...'
        #
        # RULE 14 IS THE ORDINARY CASE, NOT AN EDGE ONE. Nobody types "a
        # bracket for a 35 mm pipe, 4 mm thick, two M4 holes 60 mm apart".
        # They type "a bracket". Every number in what comes back was therefore
        # chosen rather than given, each one is a named parameter marked
        # ASSUMPTION, and that list IS what there is to change afterwards. A
        # client needs the name and the value separately to offer changing one
        # - welded into a string they are the same as absent.
        "assumptions": _assumptions_payload(part),
        "report_md": report.markdown() if hasattr(report, "markdown") else "",
        "spec": _spec_dict(spec),
        # THE NUMBERS OF AN OPS SPEC, ON THE PART THAT WAS JUST BUILT.
        #
        # _one_part sends these too, for a part opened off disk. Both are
        # needed and for the same reason the assumptions above are: a client
        # shows the BUILD RESULT immediately after building and only re-reads
        # the part later. Sent from one place, the controls would appear a
        # screen late - which is exactly when somebody wants to move them.
        "dimensions": _op_dimensions(spec),
        "files": sorted({
            f.suffix.lstrip(".").lower()
            for f in (Path(part.part_dir) / "out").glob("*")
            if f.suffix.lstrip(".").lower() in ("stl", "step", "3mf")
        }),
    }


def _op_dimensions(spec) -> list:
    """
    The draggable numbers of an ops spec, or an empty list.

    EMPTY FOR A TEMPLATE PART, on purpose: its controls are built from the
    template's parameter schema, which a client fetches by name and which
    carries defaults and choices this cannot express. Two sources for the same
    panel is a drift risk; two sources for two different KINDS of part, each
    reading the schema that actually governs it, is not.
    """
    ops = getattr(spec, "ops", None)
    if not ops:
        return []
    from whittle.spec.dsl import op_dimensions

    try:
        return op_dimensions(list(ops))
    except Exception:
        # No controls is a smaller screen. A spec this cannot read still
        # builds, still renders and still takes a sentence.
        return []


def _spec_dict(spec) -> dict:
    try:
        return json.loads(spec.model_dump_json(exclude_none=True))
    except Exception:
        try:
            return dict(spec)
        except Exception:
            return {}


def _generate_work(request: str, material: str, image_path: str | None):
    def work(job: Job) -> dict:
        from whittle import api

        def on_event(kind: str, payload: Any) -> None:
            # Translate the engine's events into something a person reads. The
            # engine's payloads are objects; putting them on the wire raw would
            # send megabytes and say nothing.
            if kind == "profile":
                job.emit("note", text="using %s on %s"
                         % (payload.model_primary, payload.name))
            elif kind == "attempt":
                job.emit("note", text="attempt %s" % getattr(payload, "index", "?"))
            elif kind == "escalate":
                job.emit("note", text="no template fits - composing from primitives")
            elif kind == "building":
                job.emit("note", text="building geometry")
            elif kind == "verified":
                # THE VERDICT, NOT JUST "CHECKED". A stage that says the
                # checks ran without saying what they found is the green tick
                # this program exists not to show, and the words are the
                # report's own.
                job.emit("note", text="verify: %s" % getattr(
                    payload, "verdict", "checked"))
            elif kind == "exporting":
                job.emit("note", text="export: writing stl, 3mf and the report")
            elif kind in ("measured", "measurement_rejected"):
                job.emit("note", text="%s from the image: %s" % (
                    "applied" if kind == "measured" else "rejected", payload))
            else:
                # A RAW EVENT NAME IS NOT A SENTENCE. This printed
                # "measurement_rejected" at somebody watching a build, which
                # is an internal identifier leaking into the one log the user
                # reads. Anything still unhandled is dropped rather than
                # shown - a silent stage beats a word nobody can act on.
                pass

        # FACTS, NOT A MEASUREMENT, and the distinction is the whole bug.
        #
        # `facts=` is a dict of things read off a reference that reaches the
        # model as CONTEXT. `measurement=` is an object whose values are
        # APPLIED to matching parameters after the build, and generate() calls
        # .as_facts() on it. This passed api.measure_image's dict into the
        # second slot, so every generate with a photo attached died on
        # "'dict' object has no attribute 'as_facts'" before it built
        # anything - image-to-part worked from the CLI and nowhere else, on
        # the one device that has a camera.
        #
        # api.reference_facts is what the CLI has always used, moved so there
        # is one of it. Its pixel caveat travels with the numbers, which
        # matters: a model given "638 wide" with no note can read it as
        # millimetres.
        facts = None
        if image_path:
            job.emit("note", text="measuring the image")
            try:
                facts = api.reference_facts(image_path)
                job.emit("note", text="measured %s"
                         % facts.get("silhouette_px", "the image"))
            except Exception as exc:
                # A photo that could not be measured is not a reason to refuse
                # to build - the words still describe a part. It is a reason to
                # say so, in the log the user is watching.
                job.emit("note", text="could not measure the image: %s" % exc)

        result = api.generate(
            request,
            material=material,
            on_event=on_event,
            facts=facts,
            render=True,
        )
        if not result.ok or result.part is None:
            return {"ok": False,
                    "message": result.message or "the model could not produce a "
                                                 "part that passes verification",
                    "attempts": result.attempt_count}

        payload = _part_payload(result.part)
        payload["ok"] = True
        payload["elapsed_s"] = round(result.elapsed_s, 1)
        payload["attempts"] = result.attempt_count

        # OPTIONS, FROM ONE MODEL CALL. The variants come from walking the
        # template's own axes in Python, so four of them cost seconds rather
        # than four more trips through a model that takes minutes and would
        # mostly repeat itself anyway. They are EMITTED as they build, so the
        # grid fills in rather than sitting empty until the last one lands.
        job.emit("note", text="building options")
        options = [{"name": payload["name"], "label": "as asked",
                    "verdict": payload["verdict"],
                    "volume_cm3": payload.get("volume_cm3"),
                    "envelope_mm": payload.get("size_mm")}]
        job.emit("option", **options[0])
        try:
            from whittle.agent.variations import build_variants

            def relay(kind, data):
                if kind == "variant_built":
                    job.emit("option", **data)
                elif kind == "variant_dropped":
                    job.emit("note", text="dropped %s - %s"
                             % (data.get("label"), data.get("why", "")[:80]))

            for variant in build_variants(result.spec, api.config(), count=4,
                                          out_root="parts", on_event=relay):
                if variant.name == payload["name"]:
                    continue
                options.append({
                    "name": variant.name, "label": variant.label,
                    "verdict": variant.verdict,
                    "volume_cm3": variant.volume_cm3,
                    "envelope_mm": list(variant.envelope_mm),
                })
        except Exception as exc:
            # Options are a bonus. Losing them must not lose the part.
            job.emit("note", text="could not build options: %s" % str(exc)[:120])

        payload["options"] = options
        return payload

    return work


#: A number of an ops spec, addressed by where it sits: "0.width_mm", or
#: "1.step.diameter_mm" for the shape a pattern repeats. See
#: dsl.op_dimensions - an ops spec has no parameter names, so position is the
#: only address there is.
_OP_ADDRESS = re.compile(r"(\d{1,3})\.(?:(step)\.)?([a-z][a-z0-9_]*)")


def _set_op_value(ops: list, address: str, value) -> tuple[str, object]:
    """
    Write one addressed number into an ops list. Returns (field, old value).

    RAISES ApiError-shaped strings via ValueError, which the worker turns into
    a sentence. Nothing is validated here beyond the address itself: the op
    models own the bounds, and `parse_op` in the rebuild is where a 1200 mm
    width is refused with the field and the limit named. A second copy of
    those rules in this file would be a second opinion that drifts.
    """
    m = _OP_ADDRESS.fullmatch(address)
    if not m:
        raise ValueError("%r is not the address of a number in this part" % address)
    index, nested, field = int(m.group(1)), m.group(2), m.group(3)
    if not (0 <= index < len(ops)):
        raise ValueError("this part has %d operations, so there is no %d"
                         % (len(ops), index))
    target = ops[index]
    if nested:
        target = target.get("step")
        if not isinstance(target, dict):
            raise ValueError("operation %d does not repeat a shape, so it has "
                             "no %s" % (index, address))
    if field not in target:
        # AN ADDRESS FOR A FIELD THE OP LEAVES AT ITS DEFAULT is not an error
        # to refuse: `corner_r_mm` absent means 0, and setting it is exactly
        # what a control is for. What must not happen is inventing a field the
        # op does not HAVE - that reaches the rebuild as "extra inputs are not
        # permitted", which is the right refusal but a worse sentence.
        from whittle.spec.dsl import parse_op, DslError
        try:
            known = type(parse_op(dict(target))).model_fields
        except DslError:
            known = {}
        if field not in known:
            raise ValueError("%s has no %s" % (target.get("op", "that operation"),
                                              field))
    was = target.get(field)
    target[field] = value
    return field, was


def _params_work(name: str, values: dict):
    """
    Rebuild a part with some of its numbers set to exactly what was asked for.

    WHY THIS EXISTS BESIDE /api/refine, WHICH ALREADY CHANGES PARTS.
    ----------------------------------------------------------------
    Refine reads a SENTENCE. That is the right way in and rule 32 says so, but
    a slider is not a sentence and turning one into a sentence is where it goes
    wrong. The parser binds a number to a field by the words near it, and the
    obvious phrasing collides: "drain dia 6mm" claims `drain_dia_mm` and
    `entrance_dia_mm` equally, because both own the word "dia" and both sit the
    same distance from the number. The parser does exactly the right thing with
    that - it asks instead of guessing - and the result is a slider that moves
    and changes nothing.

    So a control that already knows which field it is does not go through a
    parser to say so. This route takes the field names directly. Rule 32 is
    untouched: English is still the way in, and this is the implementation the
    rule says the parameters are.

    NO MODEL IS INVOLVED, which is the other reason it is separate. `api.refine`
    loads a model profile before it does anything, and a part whose numbers are
    being set does not need one - rule 11 says the system stays fully usable
    with zero model, and a slider is exactly the case where that has to hold.

    A NEW PART, NOT AN OVERWRITE. Same rule as a refine: editing never destroys
    the thing being edited, which is what makes the library a history rather
    than a single mutable object.
    """
    def work(job: Job) -> dict:
        from whittle import api
        from whittle.agent.loop import RunRecord

        job.emit("note", text="reading %s" % name)
        spec_path = api._spec_path_for(name)
        if spec_path is None:
            return {"ok": False,
                    "message": "no part called %r, or it has no spec.yaml to "
                               "change" % name}
        loaded = api.load_spec(spec_path)
        spec = loaded[0] if isinstance(loaded, tuple) else loaded

        # A PART WITH NO TEMPLATE HAS NO TEMPLATE PARAMETERS, and writing
        # some into it is not an error anything downstream notices: `params`
        # is validated against a template's model, a level-2 spec has no
        # template, so the numbers sit in the file unread. The part rebuilds
        # byte for byte, the route answers ok, and the library gains a second
        # identical entry - a slider that moves and changes nothing, which is
        # the exact failure this route was written to prevent.
        #
        # Rule 32: what was not understood is said out loud, in the words that
        # were used. Refused BEFORE the build, because the build is the
        # expensive half and its success would be the misleading part.
        addressed = [k for k in values if _OP_ADDRESS.fullmatch(k)]
        if addressed and len(addressed) != len(values):
            # ONE KIND OF NAME AT A TIME. A part is a template or a list of
            # operations, never both, so a payload holding both kinds is a
            # client mistake and half-applying it would leave a part nobody
            # asked for.
            return {"ok": False,
                    "message": "these are two different kinds of name: %s. A "
                               "part is built either from template parameters "
                               "or from operations, not both."
                               % ", ".join(sorted(values))}

        if addressed:
            ops = list(getattr(spec, "ops", None) or [])
            if not ops:
                return {"ok": False,
                        "message": "%s has no operations to change - it is "
                                   "built from a template, so its numbers are "
                                   "named rather than numbered." % name}
            changed = spec.model_copy(deep=True)
            before = {}
            try:
                for key in sorted(values):
                    _field, was = _set_op_value(changed.ops, key, values[key])
                    before[key] = was
            except ValueError as exc:
                return {"ok": False, "message": str(exc)}
        elif not getattr(spec, "template", None):
            # A PART WITH NO TEMPLATE HAS NO TEMPLATE PARAMETERS, and writing
            # some into it is not an error anything downstream notices:
            # `params` is validated against a template's model, a level-2 spec
            # has no template, so the numbers sit in the file unread. The part
            # rebuilds byte for byte, the route answers ok, and the library
            # gains a second identical entry - a slider that moves and changes
            # nothing, which is the exact failure this route was written to
            # prevent.
            #
            # Rule 32: what was not understood is said out loud, in the words
            # that were used. Refused BEFORE the build, because the build is
            # the expensive half and its success would be the misleading part.
            return {"ok": False,
                    "message": "%s is built from operations rather than "
                               "template parameters, so %s cannot be set on "
                               "it. Its own numbers are addressed by position "
                               "- see the dimensions it reports - or say what "
                               "you want changed in words."
                               % (name, ", ".join(sorted(values)))}
        else:
            before = dict(spec.params or {})
            changed = spec.model_copy(deep=True)
            changed.params = {**before, **values}

        # THE SCHEMA DECIDES, NOT THIS FUNCTION. Bounds, types and any
        # cross-field validator live on the template's params model, and a
        # refusal there is a sentence somebody can act on - "wall_mm: Input
        # should be less than or equal to 30". Checking a copy of those rules
        # here would be a second opinion that drifts.
        moved = [k for k, v in values.items() if before.get(k) != v]
        job.emit("note", text="setting %s" % ", ".join(sorted(moved)) if moved
                 else "nothing moved")

        started = time.time()
        try:
            job.emit("note", text="building the geometry")
            part = api.build(spec=changed, out_dir=api._free_part_dir(spec.name),
                             bundle=True, render=True)
        except api.ApiError as exc:
            return {"ok": False, "message": str(exc).split("\n")[0][:400]}

        job.emit("note", text="running every check")

        # RUN.JSON, SO THE PART LOOKS LIKE EVERY OTHER PART. Without it this one
        # has no stored verdict, no recorded assumptions and no provenance, and
        # opening it later shows a part that "predates the machine recording
        # verdicts" - which would be a lie about a part built a minute ago.
        RunRecord(
            request="set %s" % ", ".join(
                "%s=%s" % (k, values[k]) for k in sorted(moved)) if moved
                else "rebuilt with no change",
            machine="", started_at=str(started),
            elapsed_s=round(time.time() - started, 2),
            ok=True, level_reached=getattr(changed, "level", 1) or 1,
            spec=changed.model_dump(exclude_none=True),
            report=part.report.to_dict(),
            assumptions=[
                a.model_dump() if hasattr(a, "model_dump") else dict(a)
                for a in (getattr(part.build, "assumptions", None) or [])
            ],
        ).write(part.part_dir / "run.json")

        payload = _part_payload(part)
        payload["ok"] = True
        payload["changes"] = [
            "%s %s -> %s" % (k, before.get(k), values[k]) for k in sorted(moved)
        ]
        return payload

    return work


def _refine_work(name: str, instruction: str):
    def work(job: Job) -> dict:
        from whittle import api

        # api.refine TAKES A LOADED SPEC, NOT A NAME.
        #
        # This route passed the name straight through, so every refine died
        # inside the agent on `'str' object has no attribute 'level'` - and it
        # had never worked, because nothing exercised it until the phone's
        # command line ran `wall 3` against a real part. The web client's
        # refine box went the same way.
        #
        # Loading it here rather than widening api.refine to accept either: a
        # function that takes "a spec or the name of one" has two code paths
        # and the seldom-used one is the one that rots.
        job.emit("note", text="reading %s" % name)
        spec_path = api._spec_path_for(name)
        if spec_path is None:
            return {"ok": False,
                    "message": "no part called %r, or it has no spec.yaml to "
                               "change" % name}
        loaded = api.load_spec(spec_path)
        spec = loaded[0] if isinstance(loaded, tuple) else loaded

        def on_event(kind: str, payload) -> None:
            # A RAW EVENT NAME IS NOT A SENTENCE, and this printed "profile",
            # "closed" and "done" at somebody watching their part change. The
            # generate path fixed exactly this and refine kept the bug, because
            # nothing looked at its log until the phone had one.
            words = {
                "profile": "choosing a model",
                "building": "building the geometry",
                "verified": "running every check",
                "exporting": "writing the stl and the report",
            }
            if kind == "attempt":
                job.emit("note", text="attempt %s" % getattr(payload, "index", "?"))
            elif kind in words:
                job.emit("note", text=words[kind])
            # Anything else is internal. A silent stage beats a word nobody
            # can act on.

        result = api.refine(spec, instruction, on_event=on_event)
        if not result.ok or result.part is None:
            return {"ok": False,
                    "message": result.message or "could not apply that change"}
        payload = _part_payload(result.part)
        payload["ok"] = True
        payload["note"] = result.note
        payload["changes"] = list(result.changes)
        return payload

    return work


# ---------------------------------------------------------------------------
# rendering for the turntable
# ---------------------------------------------------------------------------


def _resolve_part(name: str) -> tuple[Path, Path | None]:
    """
    Find a part by any of the names it goes by, and its STL.

    THE SAME PART HAS TWO NAMES. `parts()` calls it by its DIRECTORY - "keyring"
    - and `library()` calls it by its SPEC name - "loop_keyring". Both are
    shown to people, both get linked, and looking a part up by only one of them
    means every link built from the other returns a 404. The STL is a third
    thing again: it is under out/ and named after the spec, not the directory.

    THE DIRECTORY WINS, AND THIS COST A PART.
    -----------------------------------------
    Accepting either name in one pass means the first entry that answers to
    the name wins, and the order is whatever the scan returns. Every edit
    keeps the spec's name, so `parts/a_hinge` holds a spec called "hinge" and
    exports `hinge.stl` - it answers to "hinge" on its STL's stem. Set a
    number on it and the rebuild landed in `parts/hinge`, a directory whose
    name IS "hinge"; asking for "hinge" got a_hinge, because it came first.

    Reading a part that way shows somebody the unchanged original they just
    asked to change - which is the failure _part_payload's "dir" field was
    added for. Deleting one that way REMOVES A DIFFERENT PART. It deleted
    parts/a_hinge, a built part, while the caller was tidying up the copy it
    had just made.

    So a directory name is matched first and on its own. It is the unique
    name, it is the one every route tells clients to navigate by, and a
    spec-name match is only consulted when no directory answers.
    """
    from whittle import api

    wanted = name.strip()
    entries = list(api.parts())

    for entry in entries:
        if entry.name == wanted:
            return Path(entry.directory), (
                Path(entry.stl) if entry.stl else None)

    for entry in entries:
        stl = Path(entry.stl) if entry.stl else None
        if stl is not None and stl.stem == wanted:
            return Path(entry.directory), stl

    # A library entry knows its directory; map back onto the same list.
    for entry in api.library():
        if entry.name == wanted and getattr(entry, "directory", None):
            directory = Path(entry.directory)
            stl = next(iter(sorted(directory.glob("out/*.stl"))), None)
            return directory, stl

    raise HttpError(404, "no part called %r" % name)


def _find_part_dir(name: str) -> Path:
    return _resolve_part(name)[0]


def _assembled_mesh(name: str):
    """
    The part AS IT IS, not as it prints.

    The STL on disk is the PRINT layout - a birdhouse is a box with its roof
    lying flat on the bed beside it, because that is how it prints without
    support. Showing that in the viewer is why the answer to "make me a
    birdhouse" looked like an open box with a slab next to it. It was a
    birdhouse the whole time, in two pieces, seen from the wrong side of the
    process.

    Templates keep the two orientations as separate functions on purpose, so
    the assembled one is there to be asked for. It costs a rebuild, which is
    seconds and happens once because the rendered frames are cached.

    An imported mesh has no spec and no assembled form; it is what it is, and
    the STL is returned.

    AND IT BUILDS INTO A THROWAWAY DIRECTORY, WHICH IT DID NOT.
    -----------------------------------------------------------
    `api.build(out_dir=None)` claims a free directory under parts/ - the right
    default for a build somebody asked for, and completely wrong here. LOOKING
    at a part in the viewer was writing a new part into the library: one
    `out/<name>.stl` and nothing else, no spec, no report, no run.json. The
    library scans directories, so each one appeared as a built part that
    cannot be rebuilt, named after the part you had just opened. That is where
    `pot_cylinder`, `enclosure_9ba7a3` and a dozen others came from - every
    one of them is somebody having turned a part around on screen.

    The mesh is wanted in memory. The files are a by-product of building one,
    so they go somewhere that is deleted on the way out.
    """
    import tempfile

    from whittle import api

    part_dir, stl = _resolve_part(name)
    spec_path = Path(part_dir) / "spec.yaml"
    if spec_path.is_file():
        try:
            loaded = api.load_spec(spec_path)
            spec = loaded[0] if isinstance(loaded, tuple) else loaded
            with tempfile.TemporaryDirectory(prefix="whittle-assembled-") as scratch:
                built = api.build(spec=spec, out_dir=Path(scratch), render=False)
                from whittle.verify.fit import mesh_of_solid

                # READ INSIDE THE BLOCK. The solid is CadQuery geometry held
                # in memory, but taking the mesh after the directory is gone
                # would be reading a result whose files have been removed, and
                # the next person to add a step here would not know which half
                # is safe.
                return mesh_of_solid(built.build.solid)
        except Exception:
            pass                        # fall back to what is on disk

    import trimesh

    if stl is None or not Path(stl).is_file():
        raise HttpError(404, "part %r has no STL yet" % name)
    mesh = trimesh.load(stl)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
    return mesh


def _render_turntable_frame(name: str, step: int, width: int, height: int,
                            layout: str = "assembled") -> bytes:
    key = (name, step, width, height, layout)
    with _RENDER_LOCK:
        hit = _RENDER_CACHE.get(key)
    if hit is not None:
        return hit

    import io

    import numpy as np
    import trimesh
    from PIL import Image

    from whittle.render.technical import render_technical

    if layout == "print":
        _part_dir, stl = _resolve_part(name)
        if stl is None or not Path(stl).is_file():
            raise HttpError(404, "part %r has no STL yet" % name)
        mesh = trimesh.load(stl)
        if isinstance(mesh, trimesh.Scene):
            mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
    else:
        mesh = _assembled_mesh(name)

    azim = 360.0 * (step % TURNTABLE_STEPS) / TURNTABLE_STEPS

    # THE DESIGN'S VIEWPORT, not a shaded grey render.
    #
    # The handoff's viewport is a technical drawing - dark `bezel` faces, white
    # feature edges, a graticule floor and three amber axis lines - and this is
    # the view BOTH clients show by default, so a shaded Lambert render made
    # the whole product look like something else. See render/technical.py.
    #
    # TRANSPARENT. The page draws its own build plate, and a flat-backed
    # render dropped on top of it reads as a hard rectangle around the part
    # because the grid stops where the picture starts. With alpha the part
    # sits ON the plate - and the technical view's own graticule is opaque
    # where it is drawn, so the two never show through each other.
    img = render_technical(
        np.asarray(mesh.vertices, dtype=float),
        np.asarray(mesh.faces),
        np.asarray(mesh.face_normals, dtype=float),
        width=width, height=height, elev_deg=26.0, azim_deg=azim,
        alpha=True,
    )
    arr = img if img.dtype == np.uint8 else (np.clip(img, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG", optimize=False)
    data = buf.getvalue()

    with _RENDER_LOCK:
        _RENDER_CACHE[key] = data
    return data


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def _checks_from_report(report: dict) -> dict:
    """
    One verify report - stored or just run - as a list a person can read.

    THE SAME FUNCTION FOR BOTH, and that is the point. A stored verdict and a
    fresh one are the same VerifyReport.to_dict shape, so rendering them
    through two code paths is how the two come to disagree about what a check
    is called or when it counts as passed.

    A LINE IS A MEASURED VALUE AND A STATUS, never a status alone. "watertight
    yes" and "worst overhang 12.4 deg" are what makes this a report rather
    than a green tick, and brief 6.7 forbids colour carrying meaning on its
    own anyway.

    `info` is a real status and not a cop-out: the number of separate bodies
    is the fact that decides whether a hinge turns, and it is neither a pass
    nor a failure - it is the measurement you have to look at.
    """
    mesh = report.get("mesh") or {}
    over = report.get("overhang") or {}
    lines: list[dict] = []

    def line(name: str, value: str, status: str) -> None:
        lines.append({"name": name, "value": value, "status": status})

    def yn(flag) -> str:
        return "yes" if flag else "no"

    if mesh:
        line("watertight", yn(mesh.get("watertight")),
             "pass" if mesh.get("watertight") else "fail")
        line("one closed volume", yn(mesh.get("is_volume")),
             "pass" if mesh.get("is_volume") else "fail")
        line("winding consistent", yn(mesh.get("winding_consistent")),
             "pass" if mesh.get("winding_consistent") else "fail")
        degenerate = int(mesh.get("degenerate_faces") or 0)
        line("degenerate faces", str(degenerate),
             "pass" if degenerate == 0 else "fail")
        # SEPARATE BODIES IS THE FACT THAT DECIDES WHETHER A HINGE TURNS.
        # Two bodies move, one is fused solid - and neither is right or wrong
        # without knowing what was asked for, so it is reported and not judged.
        if mesh.get("body_count") is not None:
            line("separate bodies", str(int(mesh["body_count"])), "info")
        bbox = mesh.get("bbox_mm")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 3:
            line("envelope",
                 "%.2f × %.2f × %.2f mm" % tuple(float(v) for v in bbox),
                 "info")
        if mesh.get("volume_cm3") is not None:
            line("volume", "%.3f cm3" % float(mesh["volume_cm3"]), "info")
        if mesh.get("face_count") is not None:
            line("triangles", str(int(mesh["face_count"])), "info")

    if over:
        worst = float(over.get("worst_overhang_deg") or 0.0)
        threshold = float(over.get("max_deg") or 45.0)
        line("worst overhang", "%.1f deg from vertical" % worst,
             "warn" if worst > threshold else "pass")
        # SUPPORT IS NOT A FAILURE. Plenty of good parts need it - the louvre
        # vent reference bridges its own aperture by design - and a verdict
        # that cries wolf on a known-good part teaches you to ignore verdicts.
        supports = bool(over.get("supports_needed"))
        line("supports needed", yn(supports), "warn" if supports else "pass")
        if over.get("unsupported_area_mm2") is not None:
            line("unsupported underside",
                 "%.2f mm2" % float(over["unsupported_area_mm2"]),
                 "warn" if float(over["unsupported_area_mm2"]) > 0 else "pass")
        if over.get("bed_area_mm2") is not None:
            line("bed contact", "%.0f mm2" % float(over["bed_area_mm2"]), "info")

    features = report.get("features") or {}
    for check in features.get("checks") or []:
        status = {"ok": "pass", "marginal": "warn", "too_fine": "fail"}.get(
            str(check.get("status")), "info")
        line("feature %s" % check.get("name"),
             "%.3f mm" % float(check.get("value_mm", 0.0)), status)

    return {
        "verdict": report.get("verdict") or ("PASS" if report.get("ok") else "FAIL"),
        "ok": bool(report.get("ok")),
        "problems": [str(p) for p in (report.get("problems") or [])],
        "warnings": [str(w) for w in (report.get("warnings") or [])],
        "nozzle_mm": report.get("nozzle_mm"),
        "material": report.get("material"),
        "print_axis": report.get("print_axis"),
        "lines": lines,
    }


def _stored_checks(part_dir: Path) -> dict | None:
    """
    The verdict this part was given when it was built.

    IT WAS THERE THE WHOLE TIME. Every part built through the pipeline writes
    run.json, and run.json carries the entire verify report - ok, the mesh
    checks, overhang, surface levels, problems, warnings. This endpoint used
    to say "a part on disk has no stored verdict, and re-verifying costs as
    long as building it". Both halves were wrong: the verdict is on disk, and
    a re-verify measured at 0.3s against a build of 151s for the same part.
    The expensive thing in a build is the model call, not the checking.

    What IS true is that a stored verdict was taken on a particular day
    against a particular printer profile. So it is served with its date and
    the nozzle and material it was measured against, and if the profile has
    moved since, this says so and the client can ask for a fresh one.
    """
    run = part_dir / "run.json"
    if not run.is_file():
        return None
    try:
        data = json.loads(run.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    report = data.get("report")
    if not isinstance(report, dict) or not report:
        return None

    checks = _checks_from_report(report)
    checks["source"] = "stored"
    checks["checked_at"] = round(run.stat().st_mtime, 3)

    # HAS THE PROFILE MOVED UNDER IT? A verdict measured against a 0.4 mm
    # nozzle says nothing certain about a machine now running 0.6, and the
    # feature-size checks are the ones that change. Only what can actually be
    # compared is compared - the stored report records the nozzle and the
    # material and not the bed, so the bed is not claimed either way.
    drift: list[str] = []
    try:
        from whittle import api

        cfg = api.config()
        now_nozzle = float(cfg.print_settings["nozzle_mm"])
        was_nozzle = checks.get("nozzle_mm")
        if was_nozzle is not None and abs(float(was_nozzle) - now_nozzle) > 1e-9:
            drift.append(
                "it was checked against a %.2f mm nozzle and the profile now "
                "says %.2f mm" % (float(was_nozzle), now_nozzle))
    except Exception:
        # A profile that cannot be read is not a reason to withhold a verdict
        # that was taken. It is a reason not to claim the verdict is current.
        drift.append("the current printer profile could not be read to "
                     "compare against")

    checks["drift"] = drift
    return checks


def _draft_payload(part_dir: Path) -> dict | None:
    """
    Why this one did not build, in the engine's own words.

    A DRAFT WAS A DEAD END IN BOTH CLIENTS. The library lists it - correctly,
    it is something you started - and opening it asked for a turntable frame
    of a part with no mesh, got a 404, and showed a screen with no size, no
    material, no checks and no exports. Nothing on it said what had happened
    or what to do next.

    Everything needed was already on disk. run.json records the request, how
    many attempts were spent on it, which models were tried and for how long,
    and the engine's diagnosis - which for a failed cut is not "invalid spec"
    but "disc in cut mode removed nothing; it sits at (20.0, 0.0, -2.0) and
    the part spans x -20.0..15.0; set z_mm to -4.00 and height_mm to 9.00".
    That is a sentence somebody can act on, and it was being thrown away.

    Returns None for a part that built, so this never appears beside a mesh.
    """
    run = part_dir / "run.json"
    if not run.is_file():
        return None
    try:
        data = json.loads(run.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("ok"):
        return None

    attempts = data.get("attempts") or []
    # dict.fromkeys rather than a set: the order the models were tried in is
    # the story - the primary first, then the smaller fallback.
    models = list(dict.fromkeys(
        str(a.get("model")) for a in attempts if a.get("model")))
    errors = [str(a.get("error")) for a in attempts if a.get("error")]

    # THE MARKED-UP SPEC, capped. It is the handoff: the closest attempt with
    # every problem written inline, and the file somebody edits by hand to
    # rescue the part. Long ones are cut rather than dropped, because the top
    # of it is the header that explains what to do.
    draft_text = ""
    draft_path = data.get("handoff") or ""
    candidates = [Path(draft_path)] if draft_path else []
    candidates += sorted(part_dir.glob("spec.draft.yaml"))
    for candidate in candidates:
        if candidate.is_file():
            draft_text = candidate.read_text()[:8000]
            draft_path = str(candidate)
            break

    return {
        "request": str(data.get("request") or ""),
        "attempts": len(attempts),
        "elapsed_s": round(float(data.get("elapsed_s") or 0.0), 1),
        "machine": str(data.get("machine") or ""),
        "models": models,
        "level_reached": data.get("level_reached"),
        # The LAST error, which is the one the run gave up on. The earlier
        # ones are attempts that were superseded, and showing four of them
        # buries the one that matters.
        "message": errors[-1] if errors else "",
        "handoff": draft_path,
        "spec_draft": draft_text,
    }


def _usage_payload() -> dict:
    """
    What this machine has actually spent, measured.

    EVERY FIGURE COMES OFF DISK. run.json records each attempt with the model
    that served it and the tokens that went in and came out, so this is a sum
    over things that happened rather than a counter somebody incremented. A
    usage screen whose numbers cannot be traced to a run is a usage screen
    nobody should believe.

    WHY THERE IS NO BALANCE HERE, AND NO PLAN. Building on this machine costs
    nothing per part: the model is local, the geometry is local, and the only
    resources spent are the seconds and the watts of the computer doing it.
    A "tokens remaining" figure would need a hosted service to be remaining
    FROM, and there is not one. Rule 29 says a value with no measured source is
    not written down, and an invented balance is exactly that.

    What IS true and worth showing: how much work has gone through, what it
    cost in model tokens, and which models did it - so that when there is a
    hosted tier, the number a person is being asked to pay for is one they have
    already watched accumulate for free.
    """
    from whittle import api

    runs = 0
    builds = 0
    drafts = 0
    prompt_tokens = 0
    gen_tokens = 0
    calls = 0
    seconds = 0.0
    models: dict[str, int] = {}
    first: float | None = None
    last: float | None = None

    for entry in api.library():
        directory = getattr(entry, "directory", None)
        if not directory:
            continue
        run = Path(directory) / "run.json"
        if not run.is_file():
            continue
        try:
            data = json.loads(run.read_text())
        except (json.JSONDecodeError, OSError):
            # A run record that will not parse is one run unaccounted for, not
            # a reason to refuse the whole total.
            continue

        runs += 1
        if data.get("ok"):
            builds += 1
        else:
            drafts += 1
        seconds += float(data.get("elapsed_s") or 0.0)

        stamp = run.stat().st_mtime
        first = stamp if first is None else min(first, stamp)
        last = stamp if last is None else max(last, stamp)

        for attempt in data.get("attempts") or []:
            model = attempt.get("model")
            if model:
                models[str(model)] = models.get(str(model), 0) + 1
            call = attempt.get("call") or {}
            if not call:
                continue
            calls += 1
            prompt_tokens += int(call.get("prompt_tokens") or 0)
            gen_tokens += int(call.get("gen_tokens") or 0)

    return {
        "runs": runs,
        "built": builds,
        "drafts": drafts,
        "model_calls": calls,
        "prompt_tokens": prompt_tokens,
        "generated_tokens": gen_tokens,
        "tokens": prompt_tokens + gen_tokens,
        "machine_seconds": round(seconds, 1),
        # Which models did the work, busiest first. A person choosing whether a
        # hosted tier is worth it wants to know what their own machine managed.
        "models": [
            {"name": name, "attempts": n}
            for name, n in sorted(models.items(), key=lambda kv: -kv[1])
        ],
        "first_run_at": round(first, 3) if first else None,
        "last_run_at": round(last, 3) if last else None,
        # THE PRICE, WHICH IS NONE, AND WHY. Said by the server rather than
        # assumed by a client, so the day there is a hosted tier this is the
        # one place that changes.
        "billable": False,
        "why_free": (
            "Everything here ran on this computer - the model, the geometry and "
            "the checks. Nothing was sent anywhere and nothing was charged."
        ),
    }


def _jobs_payload(limit: int = 12) -> list[dict]:
    """
    What the machine is working on, and what it just finished.

    THIS IS WHAT MAKES "YOU CAN LEAVE IT RUNNING" CHECKABLE. A generate runs
    on its own thread and outlives the screen that started it, which is a
    promise both clients make - and until this endpoint there was no way to
    ask what became of it. A phone that locked its screen mid-build had to
    guess from whether a part later appeared in the library.

    Read only, and it invents nothing: the elapsed time comes from the job's
    own first and last event timestamps, taken on the server's clock, and the
    note is the last thing the engine actually said rather than a stage this
    function decided the job must be at.
    """
    with JOBS_LOCK:
        jobs = list(JOBS.values())

    now = time.time()
    out = []
    for job in jobs:
        with job.lock:
            events = list(job.events)
        if not events:
            continue
        started = events[0].get("at", now)
        # A finished job's clock stops at its last event. Measuring a done job
        # against `now` would show a build from this morning as five hours
        # long, which is a wrong number rather than a stale one.
        ended = events[-1].get("at", now) if job.done else now
        notes = [e.get("text", "") for e in events if e.get("kind") == "note"]
        result = job.result or {}
        out.append({
            "id": job.id,
            "kind": job.kind,
            "request": job.request,
            "done": job.done,
            "ok": bool(result.get("ok")),
            "note": notes[-1] if notes else "",
            "name": str(result.get("name") or ""),
            "message": str(result.get("message") or ""),
            "started_at": round(started, 3),
            "elapsed_s": round(max(0.0, ended - started), 1),
        })

    # Newest first, and only a handful: this is a readout of what the machine
    # is doing, not a history, and the library is where finished parts live.
    out.sort(key=lambda row: row["started_at"], reverse=True)
    return out[:limit]


def _library_payload(entries=None, builds: dict[str, int] | None = None) -> list[dict]:
    from whittle import api

    out = []
    for entry in (api.library() if entries is None else entries):
        out.append({
            "name": entry.name,
            "dir": Path(entry.directory).name if getattr(entry, "directory", None) else entry.name,
            "template": getattr(entry, "template", None),
            "prompt": getattr(entry, "prompt", None),
            "makes": list(getattr(entry, "makes", []) or []),
            # envelope_mm, NOT bbox_mm. The library reads its sizes out of the
            # stored regression rather than loading every mesh on disk, and it
            # calls the field something different. Getting the name wrong shows
            # no size at all and looks exactly like a part that has none.
            "size_mm": [round(float(v), 1) for v in getattr(entry, "envelope_mm", [])]
            if getattr(entry, "envelope_mm", None) else None,
            "volume_cm3": getattr(entry, "volume_cm3", None),
            # PIECES. Two bodies turn, one is fused solid - which is the fact
            # the `Moving` filter and the `moves` badge are both made of. Null
            # rather than 1 when it was never recorded: a part built before the
            # baseline carried a body count has no answer, and "1 piece" for
            # it would be a guess.
            "bodies": getattr(entry, "body_count", None),
            "material": getattr(entry, "material", None),
            "level": getattr(entry, "level", None),
            "when": str(getattr(entry, "when", "") or ""),
            "built": bool(getattr(entry, "built", True)),
            # WHERE IT CAME FROM, and it changes what can be done to it.
            #
            # A part built here has a spec, so "make it taller" rebuilds it.
            # An import is somebody else's triangles: it can be hollowed, cut
            # and scaled as a mesh and it cannot be described into a different
            # shape, because there is no parametric model to change. A gallery
            # that does not know which it is holding offers one of them the
            # wrong tools.
            "origin": str(getattr(entry, "origin", "built")),
            # What the file was called when it arrived. This is how a person
            # recognises it - they downloaded "LCD-knob.stl", not "lcd-knob".
            "source_name": str(getattr(entry, "source_name", "") or ""),
            "note": str(getattr(entry, "note", "") or ""),
            "tags": [str(t) for t in (getattr(entry, "tags", None) or [])],
            # HOW MANY BUILDS THIS TILE STANDS FOR. 1 unless a chain was
            # collapsed onto it - see _newest_of_each_chain. Without it a
            # collapsed chain looks like the only build there ever was.
            "builds": int((builds or {}).get(
                Path(entry.directory).name if getattr(entry, "directory", None)
                else entry.name, 1)),
        })
    return out


#: How many parts a page holds when a client asks for paging without saying.
LIBRARY_PAGE = 60

#: What a gallery can sort by, and what each means in terms of an entry.
LIBRARY_SORTS = ("newest", "oldest", "name", "biggest", "smallest")


def _library_answer(query: dict) -> dict:
    """
    The library, searched, filtered, counted and optionally paged.

    WHY THIS GREW FROM "RETURN EVERYTHING".
    ---------------------------------------
    It returned every entry with no way to ask for less, which is correct at
    forty parts and wrong at four hundred: the whole library crosses the wire
    on every gallery open, the client filters it in JavaScript, and a phone
    draws a thousand cards nobody asked to see. The point of a gallery of a
    thousand downloaded models is finding one of them.

    PAGING IS OPT-IN, and that is deliberate. Two clients already read this
    route and both expect the lot; making pages the default would quietly
    turn both of them into apps that show the first sixty models and no hint
    there are more. A caller that passes `limit` gets a page and the numbers
    it needs to ask for the next one. A caller that does not gets exactly
    what it got before.

    THE COUNTS ARE THE PART THAT MAKES IT USABLE. `total` is the library,
    `matched` is what the query found, and `facets` is how many entries sit
    behind each filter - so a gallery can offer "brought in (318)" rather
    than a filter that might turn out to be empty. Somebody who has never
    used this should be able to see what is in it without reading anything.

    Every filter matches the library's own vocabulary, not the schema's:
    `show=made` is a part with a spec behind it, `show=brought-in` is
    somebody else's mesh, `show=unfinished` is a draft that did not build.
    """
    from whittle import api

    def one(key: str, default: str = "") -> str:
        value = query.get(key)
        return (value[0] if isinstance(value, list) else value or default).strip()

    entries = list(api.library())
    total = len(entries)

    # ONE TILE PER THING, NOT ONE PER BUILD.
    #
    # A refine writes a NEW part and leaves the old one alone, which is what
    # makes editing safe - and it means "a birdhouse", the taller one, the one
    # with the other roof and the one with 3.5 mm walls are four directories
    # reading "birdhouse". The gallery drew four identical tiles: four chances
    # to open the wrong one.
    #
    # THIS MOVED HERE FROM THE CLIENT, because it cannot be done there any
    # more. The client collapsed the list it held, and it no longer holds the
    # list - it holds page three of it, and a chain whose members straddle a
    # page boundary would collapse differently depending on where the page
    # fell. Grouping belongs where the whole library is.
    builds: dict[str, int] = {}
    if one("builds", "latest").lower() != "all":
        entries, builds = _newest_of_each_chain(entries)
        total = len(entries)

    # WHAT THE COUNTS ARE COUNTED OVER: everything this request would show
    # with no filter and no search. Facets describe the library, so they must
    # not narrow with the query - but they must agree with `total`.
    counted = list(entries)

    show = one("show", "all").lower()
    if show in ("made", "built"):
        entries = [e for e in entries
                   if getattr(e, "origin", "built") != "imported"
                   and getattr(e, "built", True)]
    elif show in ("brought-in", "brought_in", "imported"):
        entries = [e for e in entries if getattr(e, "origin", "built") == "imported"]
    elif show in ("unfinished", "drafts", "draft"):
        entries = [e for e in entries if not getattr(e, "built", True)]

    material = one("material").lower()
    if material:
        entries = [e for e in entries
                   if str(getattr(e, "material", "") or "").lower() == material]

    tag = one("tag").lower()
    if tag:
        entries = [e for e in entries
                   if tag in [str(t).lower() for t in (getattr(e, "tags", None) or [])]]

    text = one("q")
    if text:
        from whittle import library as library_mod

        # THE LIBRARY'S OWN SEARCH, not a second one written here. It matches
        # every word against the name, the template, the material, the prompt
        # that made it, the file it arrived as and the words a template says
        # it makes - which is what lets "container" find an enclosure.
        entries = library_mod.search(text, entries)

    matched = len(entries)

    sort = one("sort", "newest").lower()
    if sort not in LIBRARY_SORTS:
        sort = "newest"
    if sort == "oldest":
        entries = list(reversed(entries))
    elif sort == "name":
        entries.sort(key=lambda e: str(e.name).lower())
    elif sort in ("biggest", "smallest"):
        def bulk(entry) -> float:
            box = getattr(entry, "envelope_mm", None)
            if box and len(box) == 3:
                return float(box[0]) * float(box[1]) * float(box[2])
            return float(getattr(entry, "volume_cm3", 0.0) or 0.0) * 1000.0
        entries.sort(key=bulk, reverse=(sort == "biggest"))

    # PAGED ONLY IF ASKED. See above - the default has to stay "everything".
    offset = max(0, _as_int(one("cursor") or one("offset"), 0))
    limit = _as_int(one("limit"), 0)
    page = entries[offset:offset + limit] if limit > 0 else entries[offset:]
    shown = offset + len(page)

    return {
        "parts": _library_payload(page, builds),
        "total": total,
        "matched": matched,
        "offset": offset,
        "limit": limit or None,
        # AN OFFSET, AND IT SAYS SO. A part built while somebody is paging
        # shifts the window by one, because the order is newest first. The
        # alternative is a cursor keyed on the sort value, which is worth
        # doing when a library gets big enough for it to matter and is not
        # worth pretending to have done here.
        "next_cursor": str(shown) if limit > 0 and shown < matched else None,
        # COUNTED ON THE SAME SET THE GALLERY IS SHOWING. Facets used to be
        # counted over every build while `total` counted collapsed tiles, so
        # the chips said "made here 37" above a gallery holding 24. A number
        # on screen that does not match what is under it is worse than no
        # number.
        "facets": _library_facets(counted),
        "sort": sort,
        "show": show,
    }


def _chain_stem(directory: str) -> str:
    """A directory name with the allocator's `_2`, `_3` suffix taken off."""
    return re.sub(r"_\d+$", "", directory)


def _build_number(directory: str) -> int:
    """Which build in the chain this is. The base directory is 1, `_2` is 2."""
    match = re.search(r"_(\d+)$", directory)
    return int(match.group(1)) if match else 1


def _newest_of_each_chain(entries: list) -> tuple[list, dict[str, int]]:
    """
    The library with each chain collapsed to its latest build, order kept.

    WHERE THE LINEAGE COMES FROM. The filesystem already records it:
    `_free_part_dir` writes parts/<name>, and when that is taken,
    parts/<name>_2, parts/<name>_3 - so a chain is exactly the set of
    directories that are one base name plus an optional _<digits>.

    TWO SIGNALS, NOT ONE. The directory stem alone would group
    `birdhouse_with_feeder_and_water_retainer` with `birdhouse`, which is a
    different part somebody named separately. A chain needs the same stem AND
    the same spec name: the allocator only appends _<digits> to a name it is
    reusing, so real versions share both, and a part a person happened to call
    `foo_2` carries `foo_2` as its spec name and stays out of `foo`'s chain.

    NOTHING IS HIDDEN BY IT. Each survivor carries `builds`, the count it
    stands for, and `?builds=all` returns every one.
    """
    newest: dict[tuple, object] = {}
    order: list[tuple] = []
    counts: dict[tuple, int] = {}

    for entry in entries:
        directory = Path(getattr(entry, "directory", "") or entry.name).name
        key = (_chain_stem(directory), str(entry.name))
        counts[key] = counts.get(key, 0) + 1
        if key not in newest:
            newest[key] = entry
            order.append(key)
        else:
            held = newest[key]
            held_dir = Path(getattr(held, "directory", "") or held.name).name
            if _build_number(directory) > _build_number(held_dir):
                newest[key] = entry

    # RETURNED BESIDE THE ENTRIES, NEVER WRITTEN ONTO THEM. The scan caches
    # LibraryEntry objects and hands the same ones to every request, so
    # stamping a count on an entry here would leave it there - a later
    # `?builds=all`, which collapses nothing, would report a chain of twenty
    # on a part standing only for itself. Shared objects are read-only.
    out = [newest[key] for key in order]
    by_directory = {
        Path(getattr(newest[key], "directory", "") or newest[key].name).name: counts[key]
        for key in order
    }
    return out, by_directory


def _as_int(text: str, fallback: int) -> int:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return fallback


def _library_facets(entries: list) -> dict:
    """
    How many entries sit behind each filter.

    COUNTED ON EVERYTHING THIS REQUEST COULD SHOW - the library after chains
    are collapsed - and NOT on the filtered result. A facet is how somebody
    discovers what is here: "brought in 318" is an offer, where recomputing
    it from the filtered set would make every filter look like it had emptied
    the place. Counting it over the uncollapsed library instead was the other
    way to get it wrong, and put "made here 37" above a gallery of 24.
    """
    made = brought = unfinished = 0
    materials: dict[str, int] = {}
    tags: dict[str, int] = {}
    for entry in entries:
        imported = getattr(entry, "origin", "built") == "imported"
        if not getattr(entry, "built", True):
            unfinished += 1
        elif imported:
            brought += 1
        else:
            made += 1
        material = str(getattr(entry, "material", "") or "").lower()
        if material:
            materials[material] = materials.get(material, 0) + 1
        for raw in (getattr(entry, "tags", None) or []):
            word = str(raw).strip().lower()
            if word:
                tags[word] = tags.get(word, 0) + 1

    def ranked(counts: dict) -> list:
        return [{"name": k, "count": v}
                for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "show": {"made": made, "brought-in": brought, "unfinished": unfinished},
        "material": ranked(materials),
        # CAPPED, because tags come from files people bring in and a gallery
        # with four hundred filter chips is the problem this route is for.
        "tag": ranked(tags)[:24],
    }


def _printers_payload() -> dict:
    """
    Every machine this engine can check a part against, and what it is using.

    MEASURED AND PUBLISHED ARE BOTH LISTED, AND LABELLED. The workshop's own
    printer was measured with a tape; the rest are manufacturers'
    specifications. A client offering the list has to be able to say which
    is which, because a part 2 mm inside a published maximum is not the same
    news as one 2 mm inside a measured bed.
    """
    from whittle import api

    cfg = api.config()
    out = []
    for key, machine in sorted(cfg.printers.items(),
                               key=lambda kv: str(kv[1].get("name") or kv[0])):
        source = str(machine.get("source") or "")
        out.append({
            "key": key,
            "name": str(machine.get("name") or key),
            "bed_mm": [float(v) for v in machine.get("bed_mm", [])],
            "nozzle_mm": float(machine.get("nozzle_mm") or 0.4),
            "source": source,
            # SUBSTRING MATCHING ON A SENTENCE, AND THE FIRST TRY GOT IT
            # BACKWARDS: every published entry says "not measured here",
            # which contains the word "measured", so every printer in the
            # catalogue claimed to have been measured with a tape. The
            # negation has to be checked first.
            "measured": ("measured" in source.lower()
                         and "not measured" not in source.lower()),
        })
    return {
        "printers": out,
        # WHAT IS IN FORCE NOW, so a client can show the current one selected
        # rather than guessing from a name match.
        "using": {"name": cfg.printer_name,
                  "bed_mm": [float(v) for v in cfg.bed_mm],
                  "nozzle_mm": float((cfg.print_settings or {}).get("nozzle_mm") or 0.4)},
        "materials": list(cfg.material_names),
    }


def _print_payload(name: str, wanted_printer: str = "",
                   slice_it: bool = False) -> dict:
    """
    What is known about PRINTING this part, measured rather than estimated.

    WHY THIS IS NOT A SLICER, AND SAYS SO.
    --------------------------------------
    A slicer decides walls, infill, supports and speeds, and only then can
    anybody say how long a print takes or how much filament it uses. whittle
    does not slice and will not pretend to: a time in minutes or a figure in
    grams produced here would be a number with nothing behind it, which is
    the one thing rule 29 forbids outright.

    WHAT IS ACTUALLY KNOWN IS MOST OF WHAT YOU NEED BEFORE SLICING, and all
    of it is already measured by the time a part exists:

      * whether it fits the bed, IN ITS PRINT ORIENTATION, which is the shape
        that has to fit - the check that caught a 1248 mm birdhouse layout
      * how many layers at the layer height in force, which is division
      * whether it needs support, and how much area is unsupported - measured
        off the mesh by whittle/verify/overhang.py, not guessed from a rule
        of thumb
      * how many separate pieces come off the bed
      * the SOLID volume, stated as solid volume, because the filament a
        print actually uses depends on infill and walls and this number is
        not that

    THE LAST ONE IS THE EASIEST TO GET WRONG. Solid volume times a density
    looks like grams and is not: a 15% infill print uses a fraction of it.
    So the volume is reported as what it is and the difference is named.
    """
    from whittle import api

    part_dir, stl = _resolve_part(name)
    cfg = api.config()

    payload: dict[str, Any] = {"name": name, "ready": False}

    checks = _stored_checks(part_dir)
    stored = {}
    run = part_dir / "run.json"
    if run.is_file():
        try:
            stored = (json.loads(run.read_text()).get("report") or {})
        except (json.JSONDecodeError, OSError):
            stored = {}

    mesh = stored.get("mesh") or {}
    overhang = stored.get("overhang") or {}
    size = mesh.get("bbox_mm")
    if not size:
        regression = part_dir / "regression.json"
        if regression.is_file():
            try:
                size = json.loads(regression.read_text()).get("bbox_mm")
            except (json.JSONDecodeError, OSError):
                size = None
    # AND AN IMPORT KEEPS ITS MEASUREMENTS SOMEWHERE ELSE.
    #
    # A mesh somebody brought in has no run.json and no regression - it has
    # import.json, measured at ingest by the same code. Reading only the
    # first two told somebody that the STL they had just imported "has no
    # measured size on disk, so nothing here can be said about printing it",
    # about a file whose size is in the file beside it. Imports are the thing
    # people most want to print: they downloaded it to print it.
    if not size or len(size) != 3:
        imported = part_dir / "import.json"
        if imported.is_file():
            try:
                record = json.loads(imported.read_text())
            except (json.JSONDecodeError, OSError):
                record = {}
            size = record.get("envelope_mm")
            if size and len(size) == 3:
                mesh = {
                    "bbox_mm": size,
                    "body_count": record.get("bodies"),
                    "volume_cm3": record.get("volume_cm3"),
                    "is_volume": record.get("watertight"),
                }

    if not size or len(size) != 3:
        payload["why_not"] = (
            "%s has no measured size on disk, so nothing here can be said "
            "about printing it. A part gets one when it is built." % name)
        return payload

    size = [round(float(v), 2) for v in size]
    payload["ready"] = True
    payload["size_mm"] = size

    # THE BED, FROM THE PROFILE, and the spare room in each direction. A
    # verdict with no numbers behind it ("too big") cannot be acted on; "12 mm
    # too tall" can.
    # THE BED OF THE MACHINE BEING ASKED ABOUT, which is not always this
    # workshop's. A part checked against somebody else's bed is a verdict
    # that means nothing to the person reading it - see Config.printers.
    chosen = str(wanted_printer or "").strip()
    bed = [float(v) for v in cfg.bed_mm]
    printer_name = cfg.printer_name
    bed_source = "the printer this engine is configured for"
    if chosen:
        try:
            machine = cfg.printer_choice(chosen)
        except KeyError as exc:
            raise HttpError(400, str(exc)) from exc
        bed = [float(v) for v in machine["bed_mm"]]
        printer_name = str(machine.get("name") or chosen)
        bed_source = str(machine.get("source") or "")
    spare = [round(b - s, 2) for b, s in zip(bed, size)]
    payload["bed_mm"] = bed
    payload["spare_mm"] = spare
    payload["fits"] = all(v >= 0 for v in spare)
    payload["printer"] = printer_name
    # WHERE THE BED SIZE CAME FROM, because a measured one and a published
    # one are not the same claim and the difference decides whether a part
    # 2 mm under the limit is safe to start.
    payload["bed_source"] = bed_source

    # LAYERS: division, and the layer height that was actually used rather
    # than the config default - a spec may set its own.
    settings = dict(cfg.print_settings or {})
    layer = float(stored.get("layer_mm") or 0) or float(settings.get("layer_mm") or 0.2)
    payload["layer_mm"] = layer
    payload["layers"] = int(round(size[2] / layer)) if layer > 0 else None
    payload["nozzle_mm"] = float(
        stored.get("nozzle_mm") or settings.get("nozzle_mm") or 0.4)
    payload["material"] = stored.get("material") or None

    payload["bodies"] = mesh.get("body_count")
    payload["volume_cm3"] = (round(float(mesh["volume_cm3"]), 2)
                             if mesh.get("volume_cm3") is not None else None)
    payload["watertight"] = mesh.get("is_volume")

    if overhang:
        payload["supports_needed"] = bool(overhang.get("supports_needed"))
        payload["unsupported_mm2"] = round(
            float(overhang.get("unsupported_area_mm2") or 0.0), 1)
        payload["bed_contact_mm2"] = round(
            float(overhang.get("bed_area_mm2") or 0.0), 1)
        payload["steepest_deg"] = overhang.get("max_deg")

    payload["verdict"] = (checks or {}).get("verdict") if checks else None
    payload["files"] = sorted({
        f.suffix.lstrip(".").lower()
        for f in (part_dir / "out").glob("*")
        if f.suffix.lstrip(".").lower() in ("stl", "step", "3mf")
    })

    # WHAT A SLICER STILL HAS TO DECIDE. Said plainly, so the absence of a
    # time and a weight reads as honesty rather than as a missing feature.
    payload["for_the_slicer"] = (
        "Time and filament depend on walls, infill and speed, which a slicer "
        "decides - not this. The volume above is the solid object, and a "
        "print at 15%% infill uses a fraction of it."
    )

    # AND IF THERE IS A SLICER, ASK IT.
    #
    # Time and filament are the two things everybody wants and the two this
    # engine cannot honestly work out - so they come from a slicer, attributed
    # to it, or they do not come at all. Absent is a normal state and says
    # which package to install.
    #
    # NOT RUN UNLESS ASKED. Slicing takes seconds and a gallery that sliced
    # every part it listed would be a gallery nobody could scroll; the client
    # asks for it on the screen where somebody is deciding what to print.
    from whittle import slicing

    payload["slicer"] = {"available": slicing.which_slicer() is not None}
    if not payload["slicer"]["available"]:
        payload["slicer"]["why"] = slicing.how_to_install()
    elif slice_it and stl is not None:
        # THE DENSITY OF WHAT IT WILL BE PRINTED IN, or no weight at all.
        # The slicer's stock profile has none, so without this every part
        # comes back weighing nothing. See [materials.*].density_g_cm3 - a
        # published figure, labelled as one.
        material = str(payload.get("material") or "")
        recipe: dict[str, Any] = {}
        if material:
            try:
                recipe = cfg.material(material)
            except Exception:
                # A MATERIAL WITH AN UNSET FIELD RAISES, by design - nothing
                # downstream gets to invent a tolerance. Here that is a
                # reason to slice without a density and report no weight,
                # not a reason to fail: the time and the volume are still
                # worth having.
                recipe = {}
        density = recipe.get("density_g_cm3")
        cut = slicing.slice_part(stl, layer_mm=layer,
                                 nozzle_mm=payload["nozzle_mm"],
                                 density_g_cm3=(float(density) if density else None))
        payload["slicer"].update({
            "ok": cut.ok,
            "name": cut.slicer,
            "seconds": cut.seconds,
            "grams": cut.grams,
            "filament_mm": cut.filament_mm,
            "filament_cm3": cut.filament_cm3,
            # WHERE THE WEIGHT'S DENSITY CAME FROM, when there is a weight.
            # The slicer did the arithmetic over its own toolpaths; the
            # density is a published nominal figure, and a spool varies.
            "density_g_cm3": (float(density) if density else None),
            "density_source": str(recipe.get("density_source") or ""),
            "layers": cut.layers,
            "why": cut.why,
            # THE LINES THE FIGURES WERE READ OUT OF. A time on a screen with
            # nothing behind it is this program's claim; with these it is the
            # slicer's, and anybody can check.
            "evidence": cut.evidence,
        })
    return payload


def _part_glb(name: str) -> bytes:
    """
    The part as GLB, for a real 3D viewer.

    WHY GLB AND NOT THE STL IT ALREADY HAS. Both front ends want to orbit a
    part with their own GPU - a phone especially, where a server round trip per
    frame is the difference between turning a part and waiting for one. STL
    carries triangles and nothing else: no units, no orientation convention,
    no material, and every viewer guesses differently. glTF/GLB is the format
    those viewers actually take, one binary file, and trimesh already writes
    it - no new dependency for something this central.
    """
    cached = _GLB_CACHE.get(name)
    if cached is not None:
        return cached

    mesh = _assembled_mesh(name)

    # THE PART'S OWN COLOUR AND A REAL MATERIAL, BAKED IN.
    #
    # A mesh exported straight out of CadQuery carries neither, and glTF's
    # rule for a primitive with no material is not "pick something sensible":
    # it is baseColorFactor white, metallicFactor 1.0, roughnessFactor 1.0. A
    # fully metallic white surface is a mirror, so the part renders as whatever
    # the viewer's environment map happens to be - which is how this first
    # looked, a blown-out white silhouette with no readable form, and it looked
    # enough like a broken viewer to send the search in the wrong direction.
    #
    # So the material is declared rather than defaulted: metallic 0 because
    # this is printed plastic, roughness 0.55 because a matte surface shows
    # form through shading and a glossy one shows highlights instead, and the
    # base colour is the grey the turntable frames and the desktop viewport
    # already draw the part in. The same part must not look like two objects
    # depending on which of the three views is open.
    #
    # Vertex colours are set as well as the material. They are what a viewer
    # that ignores materials falls back to, and glTF multiplies COLOR_0 by the
    # base colour factor - both being the same grey means neither path
    # darkens the part.
    try:
        import numpy as np
        from trimesh.visual import TextureVisuals
        from trimesh.visual.material import PBRMaterial

        # raster.render's default part colour, as bytes.
        grey = np.array([158, 168, 184, 255], dtype=np.uint8)
        mesh.visual = TextureVisuals(material=PBRMaterial(
            name="whittle-part",
            baseColorFactor=(grey / 255.0).tolist(),
            metallicFactor=0.0,
            roughnessFactor=0.55,
            doubleSided=False,
        ))
        mesh.visual.vertex_attributes["color"] = np.tile(
            grey, (len(mesh.vertices), 1))
    except Exception:
        # A part that cannot carry a colour is still worth showing.
        pass

    data = mesh.export(file_type="glb")
    if isinstance(data, str):
        data = data.encode("utf-8")

    with _RENDER_LOCK:
        _GLB_CACHE[name] = data
    return data


def _health() -> dict:
    from whittle import api

    try:
        status = api.model_status()
    except Exception as exc:
        status = {"ok": False, "message": str(exc)}
    from whittle import capability

    try:
        cap = capability.detect().to_json()
    except Exception as exc:
        cap = {"tier": "unknown", "headline": "could not read this machine's "
                                              "capability: %s" % str(exc)[:100]}

    cfg = api.config()
    return {
        "model": status,
        "capability": cap,
        "render_version": RENDER_VERSION,
        "mesh_version": MESH_VERSION,
        "printer": cfg.data.get("printer", {}),
        "bed": cfg.data.get("bed", {}),
        # THE NOZZLE AND THE LAYER HEIGHT, which every verdict is measured
        # against and which no client could read. A part's stored checks carry
        # the nozzle they were taken with - that is what `drift` compares - but
        # there was no way to ask what the machine is set to NOW without
        # opening a part. The phone's first screen says what a request will be
        # measured against before it is made, and this is where that number
        # comes from.
        #
        # Straight off the config, UNSET included: rule 29 says a value with no
        # measured source reads as UNSET rather than a plausible default, and a
        # client that is handed the string can say "not set" instead of drawing
        # a nozzle nobody owns.
        "print": cfg.data.get("print", {}),
        "materials": list(cfg.material_names),
        # WHICH OF THEM IS USED WHEN NOBODY SAYS. See DEFAULT_MATERIAL: the
        # list is sorted, so a client picking its head was picking whatever
        # happened to sort first rather than what this server builds in.
        "material_default": DEFAULT_MATERIAL,
        "templates": api.templates(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "whittle"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):    # quieter than the default
        if self.path.startswith("/api/"):
            print("  %s %s" % (self.command, self.path))

    # Only the RENDERS may be cached hard. A built part's geometry never
    # changes - a refinement writes a new part - so frame 7 of a given part at
    # a given size is the same bytes forever. The HTML, CSS and JS must
    # revalidate: caching them for an hour means anyone who updates whittle keeps
    # being served the old interface until the hour is up, with no way to tell
    # that is what is happening. That is not a development annoyance, it is a
    # broken upgrade.
    # CONTENT TYPES WHOSE URLS ARE VERSIONED, AND MAY THEREFORE BE CACHED HARD.
    #
    # Every one of these is content whose bytes cannot change for a given URL:
    # a frame carries RENDER_VERSION, a GLB carries MESH_VERSION, an STL is a
    # download of a built part's geometry. Anything not listed gets no-cache,
    # which is the right default for a payload that reflects live state.
    IMMUTABLE = ("image/png", "model/stl", "model/gltf-binary")

    IMMUTABLE_CACHE = "public, max-age=604800, immutable"

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # A service worker may only control paths at or below its own
        # location, so one served from /static/ cannot control "/" unless it
        # says so. Without this the worker registers, reports success, and
        # controls nothing.
        if getattr(self, "_sw", False):
            self.send_header("Service-Worker-Allowed", "/")

        # A CALLER'S CACHE-CONTROL REPLACES THIS ONE, IT DOES NOT JOIN IT.
        #
        # These used to be two send_header calls, and the GLB route passed its
        # own - so the response went out carrying BOTH `no-cache` and
        # `public, max-age=604800, immutable`. A client reads a repeated header
        # as one comma-joined list, no-cache wins it, and the mesh was
        # refetched every single look while the code said it was cached for a
        # week. Nothing failed and nothing logged; it was just slow.
        headers = dict(extra or {})
        cache = headers.pop(
            "Cache-Control",
            self.IMMUTABLE_CACHE if ctype in self.IMMUTABLE else "no-cache",
        )
        self.send_header("Cache-Control", cache)

        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, status: int = 200):
        self._send(status, json.dumps(data).encode("utf-8"), "application/json")

    def _error(self, status: int, message: str):
        self._json({"error": message}, status=status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype == "application/json":
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HttpError(400, "body is not valid JSON: %s" % exc)
        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}

    # -- dispatch ----------------------------------------------------------

    def do_GET(self):
        try:
            self._route_get()
        except HttpError as exc:
            self._error(exc.status, exc.message)
        except BrokenPipeError:
            pass                                   # the phone went away, fine
        except Exception as exc:
            traceback.print_exc()
            self._error(500, str(exc).split("\n")[0][:300])

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        try:
            self._route_post()
        except HttpError as exc:
            self._error(exc.status, exc.message)
        except BrokenPipeError:
            pass
        except Exception as exc:
            traceback.print_exc()
            self._error(500, str(exc).split("\n")[0][:300])

    def _route_get(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        query = parse_qs(url.query)

        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])

        if path == "/api/health":
            return self._json(_health())
        if path == "/api/parts":
            return self._json(_library_answer(query))
        m = re.fullmatch(r"/api/part/([^/]+)/print", path)
        if m:
            asked = query.get("printer")
            wants = query.get("slice")
            return self._json(_print_payload(
                m.group(1), (asked[0] if asked else "") or "",
                slice_it=bool(wants and wants[0] not in ("0", "false", "no"))))

        if path == "/api/printers":
            return self._json(_printers_payload())

        if path == "/api/usage":
            return self._json(_usage_payload())
        if path == "/api/jobs":
            return self._json({"jobs": _jobs_payload()})
        if path == "/api/operations":
            from whittle.web import projects as P

            return self._json(P.catalogue())

        # -- editing sessions, v8 M4 ---------------------------------------
        m = re.fullmatch(r"/api/project/([0-9a-f]{6,32})", path)
        if m:
            return self._json(self._project(m.group(1)).payload())

        m = re.fullmatch(r"/api/project/([0-9a-f]{6,32})/preview", path)
        if m:
            from whittle.web import projects as P

            project = self._project(m.group(1))
            with P.PROJECTS.lock(project.id):
                mesh, simplified = P.preview_mesh(project)
                data = P.to_glb(mesh)
            # NEVER CACHED. The whole point is that it changes on every drag,
            # and a preview served from a cache is last slider position.
            return self._send(200, data, "model/gltf-binary",
                              {"Cache-Control": "no-store",
                               "X-Preview-Simplified": "1" if simplified else "0"})

        m = re.fullmatch(r"/api/project/([0-9a-f]{6,32})/export\.(stl|glb)", path)
        if m:
            from whittle.web import projects as P

            project = self._project(m.group(1))
            with P.PROJECTS.lock(project.id):
                # THE FULL MESH, never the proxy. The proxy is for looking at.
                mesh = project.evaluate()
                if m.group(2) == "glb":
                    data, ctype = P.to_glb(mesh), "model/gltf-binary"
                else:
                    data, ctype = mesh.export(file_type="stl"), "model/stl"
            name = Path(project.source.path.name).stem
            return self._send(200, data, ctype, {
                "Cache-Control": "no-store",
                "Content-Disposition":
                    'attachment; filename="%s-whittle.%s"' % (name, m.group(2)),
            })

        m = re.fullmatch(r"/api/template/([^/]+)", path)
        if m:
            return self._json(self._template(m.group(1)))

        m = re.fullmatch(r"/api/part/([^/]+)", path)
        if m:
            return self._json(self._one_part(m.group(1)))

        m = re.fullmatch(r"/api/part/([^/]+)/stl", path)
        if m:
            return self._send_stl(m.group(1))

        m = re.fullmatch(r"/api/part/([^/]+)/glb", path)
        if m:
            return self._send_glb(m.group(1))

        m = re.fullmatch(r"/api/part/([^/]+)/render/([a-z]{1,12})", path)
        if m:
            return self._send_render(m.group(1), m.group(2))

        m = re.fullmatch(r"/api/part/([^/]+)/file/([a-z0-9]{1,6})", path)
        if m:
            return self._send_file(m.group(1), m.group(2))

        m = re.fullmatch(r"/api/part/([^/]+)/frame/(\d+)", path)
        if m:
            name, step = m.group(1), int(m.group(2))
            self._check_name(name)
            size = int((query.get("w") or ["640"])[0])
            size = max(160, min(1200, size))
            layout = (query.get("layout") or ["assembled"])[0]
            layout = "print" if layout == "print" else "assembled"
            data = _render_turntable_frame(name, step, size,
                                           int(size * 0.78), layout)
            return self._send(200, data, "image/png")

        m = re.fullmatch(r"/api/job/([0-9a-f]+)/events", path)
        if m:
            return self._sse(m.group(1))

        m = re.fullmatch(r"/api/job/([0-9a-f]+)", path)
        if m:
            job = JOBS.get(m.group(1))
            if job is None:
                raise HttpError(404, "no such job")
            return self._json({"id": job.id, "done": job.done,
                               "result": job.result, "events": job.events})

        raise HttpError(404, "no route for %s" % path)

    # WHAT MAY BE UPLOADED AS A REFERENCE PHOTO. An allow-list, and checked
    # against the file's own magic bytes rather than its name: an extension is
    # a claim made by whoever named the file.
    IMAGE_MAGIC = {
        b"\xff\xd8\xff": ("jpg", "image/jpeg"),
        b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
        b"RIFF": ("webp", "image/webp"),
    }

    # A phone camera photo is a few megabytes. Ten is generous and stops a
    # mistake - or a stray POST - from filling the disk.
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024

    def _route_post(self):
        path = urlparse(self.path).path

        # BEFORE _body(). An upload is raw bytes, and _body() would try to
        # parse a JPEG as JSON.
        if path == "/api/upload":
            return self._receive_image()

        if path == "/api/project":
            return self._receive_model()

        if path == "/api/library/model":
            return self._receive_into_library()

        body = self._body()

        # `body`, not self._body() again. _body() reads Content-Length bytes off
        # the socket, and a second call blocks for ever waiting for bytes the
        # client already sent and will not send twice - the request simply
        # hangs, with no error on either side until something times out.
        if path == "/api/command":
            return self._json(self._command(body))

        if path == "/api/generate":
            request = (body.get("request") or "").strip()
            if not request:
                raise HttpError(400, "say what you want made")
            material = (body.get("material") or DEFAULT_MATERIAL).strip().lower()
            image = body.get("image_path") or None
            job = _start_job("generate", request,
                             _generate_work(request, material, image))
            return self._json({"job": job.id})

        # -- editing sessions, v8 M4 ---------------------------------------
        m = re.fullmatch(r"/api/project/([0-9a-f]{6,32})/edit", path)
        if m:
            from whittle.web import projects as P

            project = self._project(m.group(1))
            kind = (body.get("kind") or "").strip()
            with P.PROJECTS.lock(project.id):
                return self._json(
                    self._edited(P.add_edit, project, kind, body.get("values")))

        m = re.fullmatch(r"/api/project/([0-9a-f]{6,32})/edit/([0-9a-f]{4,16})",
                         path)
        if m:
            from whittle.web import projects as P

            project = self._project(m.group(1))
            op_id = m.group(2)
            with P.PROJECTS.lock(project.id):
                if "enabled" in body:
                    return self._json(
                        self._edited(P.toggle, project, op_id,
                                     bool(body["enabled"])))
                if body.get("remove"):
                    return self._json(
                        self._edited(P.remove, project, op_id))
                name = (body.get("name") or "").strip()
                if not name:
                    raise HttpError(
                        400, "say which parameter to change, as "
                             '{"name": "wall_mm", "value": 2.0}')
                # `final` is pointer-up. While the thumb is down the
                # geometry updates and the verdict waits - see set_value.
                return self._json(
                    self._edited(P.set_value, project, op_id, name,
                                 body.get("value"), bool(body.get("final"))))

        if path == "/api/project/from-part":
            # A PART THIS MACHINE BUILT, OPENED AS AN EDIT SESSION. The mesh is
            # read off disk rather than sent up from the phone and back down:
            # same ingest, same gate, same operations as an import, without a
            # round trip for bytes that never left the machine.
            from whittle import api
            from whittle.web import projects as P

            name = (body.get("name") or "").strip()
            self._check_name(name)
            part_dir, stl = _resolve_part(name)
            if stl is None:
                raise HttpError(
                    404, "%r has no mesh on disk to edit - it may have been "
                         "built before its STL was written" % name)

            cfg = api.config()
            nozzle = float(cfg.print_settings["nozzle_mm"])
            bed = cfg.data.get("bed", {})
            bed_mm = None
            if all(bed.get(k) for k in ("width_mm", "depth_mm", "height_mm")):
                bed_mm = (float(bed["width_mm"]), float(bed["depth_mm"]),
                          float(bed["height_mm"]))

            try:
                project = P.open_part(Path(stl), nozzle_mm=nozzle, bed_mm=bed_mm)
            except FileNotFoundError as exc:
                raise HttpError(404, str(exc)) from exc
            except Exception as exc:
                raise HttpError(422, str(exc).split("\n")[0][:300]) from exc
            return self._json(project.payload())

        m = re.fullmatch(r"/api/project/([0-9a-f]{6,32})/say", path)
        if m:
            from whittle.web import projects as P

            project = self._project(m.group(1))
            sentence = (body.get("sentence") or "").strip()
            if not sentence:
                raise HttpError(400, "say what to do")
            with P.PROJECTS.lock(project.id):
                return self._json(self._edited(P.say, project, sentence))

        m = re.fullmatch(r"/api/part/([^/]+)/verify", path)
        if m:
            return self._json(self._reverify(m.group(1)))

        if path == "/api/refine":
            name = (body.get("name") or "").strip()
            instruction = (body.get("instruction") or "").strip()
            self._check_name(name)
            if not instruction:
                raise HttpError(400, "say what to change")
            job = _start_job("refine", instruction, _refine_work(name, instruction))
            return self._json({"job": job.id})

        m = re.fullmatch(r"/api/part/([^/]+)/delete", path)
        if m:
            return self._json(self._delete_part(m.group(1)))

        m = re.fullmatch(r"/api/part/([^/]+)/rename", path)
        if m:
            wanted = (body.get("name") or "").strip()
            return self._json(self._rename_part(m.group(1), wanted))

        m = re.fullmatch(r"/api/part/([^/]+)/params", path)
        if m:
            # A SLIDER, WHICH IS NOT A SENTENCE. See _params_work for why this
            # does not go through the language layer and why it needs no model.
            name = m.group(1)
            self._check_name(name)
            values = body.get("values")
            if not isinstance(values, dict) or not values:
                raise HttpError(400, 'send {"values": {"width_mm": 150}}')
            if len(values) > 64:
                raise HttpError(400, "that is more parameters than any template has")
            for key, value in values.items():
                # EITHER A TEMPLATE PARAMETER NAME OR AN OPS ADDRESS.
                # "wall_mm" names a field on a template's parameter model;
                # "1.step.diameter_mm" names a number inside an ops spec,
                # which has no parameter names at all and so is addressed by
                # position. See _OP_ADDRESS and dsl.op_dimensions.
                if not isinstance(key, str) or not (
                        key.replace("_", "").isalnum()
                        or _OP_ADDRESS.fullmatch(key)):
                    raise HttpError(400, "%r is not a parameter name" % key)
                # The schema does the real checking. What is refused here is
                # anything that is not a value at all - a list, an object, a
                # nested payload - because those reach the template as a type
                # error rather than as a sentence about a dimension.
                if not isinstance(value, (int, float, str, bool)):
                    raise HttpError(400, "%s must be a number, a word or true/false" % key)
            job = _start_job(
                "params",
                "set %s" % ", ".join(sorted(values)),
                _params_work(name, values),
            )
            return self._json({"job": job.id})

        raise HttpError(404, "no route for %s" % path)

    # A MODEL, NOT A PHOTO. Bigger limit than the reference-image route: a
    # download off Printables is routinely tens of megabytes, and the real
    # constraint is triangles rather than bytes - a binary STL and the same
    # geometry as ASCII differ about fivefold for an identical model.
    MAX_MODEL_BYTES = 150 * 1024 * 1024

    def _project(self, project_id: str):
        from whittle.web import projects as P

        try:
            return P.PROJECTS.get(project_id)
        except KeyError as exc:
            raise HttpError(404, str(exc)) from exc

    @staticmethod
    def _edited(fn, *args):
        """
        Run one edit and turn its refusals into answers.

        An EditError is the user asking for something the geometry cannot do -
        a wall thicker than the model, a cut outside it - and the message
        already says which and why. A 422 with that message is the right
        answer; a 500 with a traceback is not.
        """
        from whittle.edit import EditError

        try:
            return fn(*args)
        except EditError as exc:
            raise HttpError(422, str(exc)) from exc

    def _receive_into_library(self):
        """
        Take a model straight into the library, measured, without opening it.

        WHY THIS IS NOT /api/project. That route opens an EDITING SESSION on
        an upload and deliberately files it in a temporary directory, because
        a mesh somebody is editing is not yet a part they have decided to
        keep. That is the right shape for "bring this in and work on it" and
        the wrong shape entirely for "here are two hundred STLs I downloaded":
        two hundred editing sessions, each holding a mesh in memory, none of
        them wanted.

        `api.import_stl` has done exactly this since it was written -
        measures the mesh, tries the revolve and prism fitters so the thing
        can be EDITED later rather than only viewed, writes import.json - and
        nothing had a door onto it. This is the door.

        TAGS COME FROM THE CLIENT AND ARE NOT INFERRED. A file called
        `knob_v3_final.stl` says nothing reliable about whether it came from
        Printables or Thingiverse, and rule 9 says do not guess: whoever is
        doing the importing knows, and a wrong tag on two hundred models is
        worse than none.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise HttpError(400, "no model in the body")
        if length > self.MAX_MODEL_BYTES:
            raise HttpError(
                413, "that file is %.1f MB and the limit is %d MB"
                % (length / 1048576.0, self.MAX_MODEL_BYTES // 1048576))

        name = (self.headers.get("X-Filename") or "model.stl").strip()
        name = Path(name).name or "model.stl"
        if not SAFE_NAME.fullmatch(name):
            raise HttpError(400, "%r is not a plain file name" % name)

        # COMMA-SEPARATED, LOWERCASED, AND CAPPED. These become filter chips
        # in a gallery; a file carrying forty of them is a row of controls
        # nobody can read past.
        raw_tags = (self.headers.get("X-Tags") or "").strip()
        tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()][:8]
        for tag in tags:
            if not re.fullmatch(r"[a-z0-9][a-z0-9 _-]{0,30}", tag):
                raise HttpError(400, "%r is not a tag" % tag)

        note = (self.headers.get("X-Note") or "").strip()[:400]

        payload = self.rfile.read(length)

        from whittle import api

        try:
            record = api.import_stl(name, data=payload, tags=tags, note=note)
        except api.ApiError as exc:
            # A FILE THAT IS NOT A MODEL IS A 400, not a 500: "that is not a
            # format this takes" is an answer, and a batch importer needs to
            # be able to tell "skip this one" from "the engine fell over".
            raise HttpError(400, str(exc).split("\n")[0][:300]) from exc

        # THE LIBRARY HAS CHANGED, and the scan caches on what it last saw.
        # A new directory appears with a new fingerprint so it would be
        # noticed anyway; saying so directly means the next request does not
        # have to discover it.
        from whittle import library as library_mod

        library_mod.forget()

        return self._json({"ok": True, "part": record})

    def _receive_model(self):
        """
        Take a mesh in and open an editing session on it.

        The file is written to a temporary directory rather than the library:
        an import being EDITED is not yet a part somebody keeps, and filing it
        before they have decided would fill the library with abandoned
        uploads.
        """
        import tempfile

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise HttpError(400, "no model in the body")
        if length > self.MAX_MODEL_BYTES:
            raise HttpError(
                413, "that file is %.1f MB and the limit is %d MB"
                % (length / 1048576.0, self.MAX_MODEL_BYTES // 1048576))

        name = (self.headers.get("X-Filename") or "model.stl").strip()
        name = Path(name).name or "model.stl"
        if not SAFE_NAME.fullmatch(name):
            raise HttpError(
                400, "%r is not a plain file name" % name)

        payload = self.rfile.read(length)
        folder = Path(tempfile.mkdtemp(prefix="whittle-project-"))
        target = folder / name
        target.write_bytes(payload)

        from whittle import api
        from whittle.ingest.formats import UnsupportedFormat
        from whittle.web import projects as P

        cfg = api.config()
        nozzle = float(cfg.print_settings["nozzle_mm"])
        bed = cfg.data.get("bed", {})
        bed_mm = None
        if all(bed.get(k) for k in ("width_mm", "depth_mm", "height_mm")):
            bed_mm = (float(bed["width_mm"]), float(bed["depth_mm"]),
                      float(bed["height_mm"]))

        try:
            project = P.PROJECTS.open(target, nozzle_mm=nozzle, bed_mm=bed_mm,
                                      units=self.headers.get("X-Units") or None)
        except UnsupportedFormat as exc:
            raise HttpError(415, str(exc)) from exc
        except Exception as exc:
            raise HttpError(422, str(exc).split("\n")[0][:300]) from exc

        return self._json(project.payload())

    def _receive_image(self):
        """
        Take a reference photo and say where it landed.

        The client posts the raw bytes and gets back a path it can hand to
        /api/generate as `image_path`. That endpoint has always accepted a
        path and there was never a way to put a file at one - so image-to-model
        worked from the command line and nowhere else, which on a phone is the
        one device with a camera.

        THE FILE IS NOT TRUSTED. Its declared name is discarded except for an
        extension check, the real type comes from the magic bytes, and the
        name it is saved under is generated here. A filename that arrives over
        the wire is somebody else's string.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise HttpError(400, "no image in the body")
        if length > self.MAX_UPLOAD_BYTES:
            raise HttpError(
                413, "that image is %.1f MB and the limit is %d MB"
                % (length / 1048576.0, self.MAX_UPLOAD_BYTES // 1048576))

        payload = self.rfile.read(length)
        kind = next(
            ((ext, mime) for magic, (ext, mime) in self.IMAGE_MAGIC.items()
             if payload.startswith(magic)),
            None,
        )
        if kind is None:
            raise HttpError(
                400, "that is not a JPEG, PNG or WebP - the first bytes say "
                     "otherwise, whatever the file is called")
        ext, mime = kind

        from whittle.imports import IMPORT_ROOT

        target_dir = Path(IMPORT_ROOT) / "uploads"
        target_dir.mkdir(parents=True, exist_ok=True)
        # The name is generated, never taken from the request: a filename off
        # the wire is where path traversal lives.
        name = "ref-%d.%s" % (int(time.time() * 1000), ext)
        target = target_dir / name
        target.write_bytes(payload)

        # Measure it now, so the client can show what was actually read off
        # the picture before spending minutes on a generate. A photo that
        # separated nothing from its background is worth saying so about
        # immediately.
        from whittle import api

        facts: dict[str, Any] = {}
        note = ""
        try:
            # measure_image returns Box objects for the regions it found, which
            # carry their own repr and do not serialise. Kept as their readable
            # form rather than exploded into four numbers: the client shows
            # them to a person, and "L17 R654 T13 B696 (638 x 684 px)" is what
            # a person wants to read.
            facts = {
                key: (value if isinstance(value, (int, float, str, bool, type(None)))
                      else str(value))
                for key, value in api.measure_image(target).items()
            }
        except Exception as exc:
            note = str(exc)[:200]

        return self._json({
            "path": str(target),
            "name": name,
            "bytes": len(payload),
            "type": mime,
            "measured": facts,
            "note": note,
            # THE HONEST CAVEAT, carried with the measurement rather than left
            # for the UI to remember: every figure above is in PIXELS. Nothing
            # here can become a millimetre without one real dimension from the
            # person holding the object.
            "needs_scale": bool(facts),
        })

    # -- helpers -----------------------------------------------------------

    def _check_name(self, name: str):
        # Part names reach the filesystem. Anything that is not a plain name is
        # refused outright rather than sanitised - sanitising is where path
        # traversal bugs live.
        if not SAFE_NAME.fullmatch(name or ""):
            raise HttpError(400, "%r is not a valid part name" % name)

    def _static(self, rel: str):
        self._sw = rel.endswith("sw.js")
        if ".." in rel or rel.startswith("/"):
            raise HttpError(400, "bad path")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            raise HttpError(400, "bad path")
        if not target.is_file():
            raise HttpError(404, "no file %r" % rel)
        ctype = (EXTRA_TYPES.get(target.suffix.lower())
                 or mimetypes.guess_type(str(target))[0]
                 or "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    def _one_part(self, name: str) -> dict:
        self._check_name(name)
        from whittle import api

        part_dir, stl = _resolve_part(name)
        payload: dict[str, Any] = {"name": name, "frames": TURNTABLE_STEPS}

        spec_path = part_dir / "spec.yaml"
        if spec_path.is_file():
            # load_spec returns (PartSpec, base_dir), not a PartSpec. Passing
            # the tuple straight to the serialiser produced "{}" and an empty
            # Spec tab that looked like a part with no spec.
            loaded = api.load_spec(spec_path)
            spec_obj = loaded[0] if isinstance(loaded, tuple) else loaded
            payload["spec"] = _spec_dict(spec_obj)
            payload["level"] = getattr(spec_obj, "level", None)
            payload["template"] = getattr(spec_obj, "template", None)
            payload["material"] = getattr(spec_obj, "material", None)

            # THE NUMBERS OF AN OPS SPEC, as controls.
            #
            # A template part gets its sliders from the template's parameter
            # model, which the app fetches by name. A level-2 part has no
            # template, so the app asked for a schema, got nothing, and showed
            # no controls at all - for most of what whittle generates. Rule 32
            # puts English first and says the parameters are how it is
            # implemented; there was no implementation to reach.
            #
            # SERVED WITH THE PART rather than derived in the client: the
            # bounds live on the op models, the app cannot see them, and a
            # second copy of the DSL's schema in TypeScript is the kind of
            # thing that drifts silently. See dsl.op_dimensions for what is
            # offered and what is left out.
            payload["dimensions"] = _op_dimensions(spec_obj)

        report_md = part_dir / "report.md"
        if report_md.is_file():
            payload["report_md"] = report_md.read_text()

        # Sizes come from the stored regression, which is what the library
        # reads too, so the card and the opened part cannot disagree.
        regression = part_dir / "regression.json"
        if regression.is_file():
            try:
                data = json.loads(regression.read_text())
                if data.get("bbox_mm"):
                    payload["size_mm"] = [round(float(v), 1) for v in data["bbox_mm"]]
                if data.get("volume_cm3") is not None:
                    payload["volume_cm3"] = round(float(data["volume_cm3"]), 1)
                # PIECES. For anything with a moving part this is the fact that
                # decides whether it works: two bodies turn, one body is fused
                # solid. The app had no way to show it for a part opened from
                # the library, which is the only way you ever look at one
                # again.
                if data.get("body_count"):
                    payload["bodies"] = int(data["body_count"])
            except Exception:
                pass

        # THE VERDICT IT WAS GIVEN, with the day it was given and the profile
        # it was measured against.
        #
        # This used to say "a part on disk has no stored verdict, and the only
        # honest answers are to re-verify it - which takes as long as building
        # it - or to say nothing". Both halves were false. run.json holds the
        # entire verify report, and a re-verify of a real part measured 0.3s
        # against that part's own recorded build time of 151s - the model call
        # is what a build costs, not the checking. The result was two clients
        # printing "not re-checked" over an answer that was sitting in the
        # part's own directory.
        #
        # Absent when the part predates run.json or was imported rather than
        # generated, which is a real "not known" and says so.
        checks = _stored_checks(part_dir)
        if checks is not None:
            payload["checks"] = checks

        # WHY IT DID NOT BUILD, for the ones that did not. See _draft_payload:
        # opening one of these used to be a dead end with a 404 render on it.
        draft = _draft_payload(part_dir)
        if draft is not None:
            payload["draft"] = draft

        # AN IMPORTED MESH, WHICH HAS NO SPEC AND IS NOT EMPTY.
        #
        # `_one_part` reads spec.yaml, run.json and regression.json - all three
        # of which a part built here writes and an import writes none of. So
        # opening an imported STL returned a name, a frame count and nothing
        # else: no size, no volume, no piece count, on a screen whose whole job
        # is to show those.
        #
        # Every one of them is in import.json, measured at ingest by the same
        # code a built part's regression uses. It was being read for the
        # library list and not for the part itself.
        imported = part_dir / "import.json"
        if imported.is_file():
            try:
                record = json.loads(imported.read_text())
            except (json.JSONDecodeError, OSError):
                record = {}
            payload["origin"] = "imported"
            payload["source_name"] = str(record.get("source_name") or "")
            payload["note"] = str(record.get("note") or "")
            payload["tags"] = [str(t) for t in (record.get("tags") or [])]
            envelope = record.get("envelope_mm")
            if isinstance(envelope, (list, tuple)) and len(envelope) == 3:
                payload["size_mm"] = [round(float(v), 1) for v in envelope]
            if record.get("volume_cm3") is not None:
                payload["volume_cm3"] = round(float(record["volume_cm3"]), 1)
            if record.get("bodies") is not None:
                payload["bodies"] = int(record["bodies"])
            if record.get("triangles") is not None:
                payload["triangles"] = int(record["triangles"])
            if record.get("watertight") is not None:
                payload["watertight"] = bool(record["watertight"])
            # WHY IT CANNOT BE FITTED TO A TEMPLATE, when the importer worked
            # it out. "not a turned shape: cross-sections vary by 52.7% around
            # the axis" is the sentence that explains why this one gets mesh
            # operations rather than sliders, and it was being thrown away.
            if record.get("fit_note"):
                payload["fit_note"] = str(record["fit_note"])
        else:
            payload["origin"] = "built"

        # WHAT WAS CHOSEN RATHER THAN GIVEN, for a part nobody has just built.
        #
        # The same list the build result carries, off disk. It is the panel a
        # person changes things from after typing a two-word request, and the
        # library is the only way they ever see the part again - so serving it
        # only on the fresh build made rule 14's marked parameters last about
        # as long as one screen.
        #
        # Empty for anything built before run.json recorded them, which is a
        # true "none recorded" rather than a claim that none were made.
        payload["assumptions"] = _stored_assumptions(part_dir)

        # The same identity the build result carries, for the same reason: two
        # parts can share a spec name and only the directory tells them apart.
        payload["dir"] = part_dir.name
        payload["has_stl"] = stl is not None and Path(stl).is_file()
        payload["files"] = sorted({
            f.suffix.lstrip(".").lower()
            for f in (part_dir / "out").glob("*")
            if f.suffix.lstrip(".").lower() in self.DOWNLOADABLE
        })
        return payload

    def _reverify(self, name: str) -> dict:
        """
        Check this part again, now, against the profile as it stands today.

        SYNCHRONOUS, BECAUSE IT IS CHEAP. This is not a build: no model is
        called and no geometry is composed. It loads the mesh that is already
        on disk and runs the same checks the build ran - measured at 0.3s on a
        real part whose build took 151s. Putting it on the job queue would
        mean a spinner, an event stream and a screen state for something that
        finishes before the phone has finished animating.

        It does not write anything. A re-check is a reading, and overwriting
        run.json would destroy the record of what the part was given when it
        was made - which is exactly the provenance the report tab is for.
        """
        self._check_name(name)
        from whittle import api

        part_dir, stl = _resolve_part(name)
        if stl is None or not Path(stl).is_file():
            raise HttpError(
                409, "%s has no mesh to check - it is a draft, and there is "
                     "nothing on disk to measure" % name)

        material = None
        spec_path = part_dir / "spec.yaml"
        if spec_path.is_file():
            try:
                loaded = api.load_spec(spec_path)
                spec_obj = loaded[0] if isinstance(loaded, tuple) else loaded
                material = getattr(spec_obj, "material", None)
            except Exception:
                # The material only labels the report. A spec that will not
                # load is a reason to check the mesh without it, not a reason
                # to refuse to check the mesh.
                pass

        try:
            report = api.verify(str(stl), material=material)
        except api.ApiError as exc:
            raise HttpError(422, str(exc))

        checks = _checks_from_report(report.to_dict())
        checks["source"] = "just now"
        checks["checked_at"] = round(time.time(), 3)
        # Nothing has drifted from a check taken against the profile as it is
        # this second, which is the whole reason to offer one.
        checks["drift"] = []
        return {"name": name, "checks": checks}

    def _template(self, name: str) -> dict:
        """
        A template described as data: every parameter with its type, default,
        bounds, units and description.

        THIS IS WHERE THE SLIDERS' MIN AND MAX COME FROM, and it is the reason
        this route exists rather than the clients carrying a table. The bounds
        are the Pydantic schema's own - `wall_mm` is `gt=0.4, le=30.0` because
        that is what the template accepts - so a slider cannot offer a value
        the builder will reject, and a new template gets a working parameter
        form with no client change at all.

        A client inventing its own ranges would be guessing at a dimension,
        which is the one thing this project does not do.
        """
        self._check_name(name)
        from whittle import api

        try:
            return api.template_info(name)
        except api.ApiError as exc:
            raise HttpError(404, str(exc))

    def _command(self, body: dict) -> dict:
        """
        Parse one command-line entry. Brief 6.4, design handoff.

        ONE PARSER, SHARED. The handoff says the command line must genuinely
        parse and must use the composer's parser rather than its own. Written
        in each client, `wall 3` would mean one thing in the browser and
        another on the phone - the same class of bug as a colour that differs
        between clients, except this one changes geometry.

        The parse itself is whittle.agent.command. What is added here is the one
        thing the parser deliberately does not hold: the answer to a question,
        which comes from the machine's own profile.
        """
        from whittle.agent import command as parser

        line = body.get("line")
        if not isinstance(line, str):
            raise HttpError(400, "send a command as {\"line\": \"wall 3\"}")
        if len(line) > 400:
            raise HttpError(400, "that is longer than a command line")

        parsed = parser.parse(line)
        payload = parsed.to_json()

        if parsed.kind == "ask":
            payload["echo"] = self._answer(parsed.topic,
                                           body.get("material") or DEFAULT_MATERIAL)

        return payload

    def _answer(self, topic: str | None, material: str) -> str:
        """
        Answer a `<topic> ?` from the machine's real configuration.

        AND SAY WHERE THE NUMBER CAME FROM. Brief 4.3 forbids stating a
        clearance as if it were calibrated when it is a conservative default,
        because a maker who believes a number is measured designs to it. There
        is no calibration record in config yet, so every clearance this can
        answer with is a default and it says so - and when a calibration flow
        lands, this is the one place that sentence changes.

        An UNSET value is not a missing feature either: TPU's clearance is
        deliberately unset because nothing measured it, and reading one raises
        rather than substituting a guess (CLAUDE.md 29). The honest answer is
        that nobody has measured it.
        """
        from whittle import api
        from whittle.agent.loop import running_clearance_mm

        if topic != "clearance":
            return "%s - nothing here answers that yet" % topic

        cfg = api.config()
        value = running_clearance_mm(cfg, material)
        if value is None:
            return ("clearance for %s has no measured source - print the "
                    "calibration strip and it becomes a real number" % material)

        return ("clearance %.2f mm - a conservative default for %s, not from "
                "a calibration strip" % (value, material))

    def _send_glb(self, name: str):
        """
        The part as one GLB. Marked immutable like the render frames: for one
        part at one MESH_VERSION the bytes never change, so a viewer may cache
        it hard and a second look costs nothing.

        The version lives in the client's query string rather than in this
        method, because a hard cache is keyed on the URL: see MESH_VERSION.
        The parameter is ignored here on purpose - it exists to make the URL
        different, and nothing about the response depends on reading it.
        """
        self._check_name(name)
        try:
            data = _part_glb(name)
        except FileNotFoundError as exc:
            raise HttpError(404, str(exc))
        # The immutable header comes from the content type now, not from here:
        # passing it here sent it twice and no-cache won. See _send.
        self._send(200, data, "model/gltf-binary", {
            "Content-Disposition": 'inline; filename="%s.glb"' % name,
        })

    def _send_stl(self, name: str):
        self._check_name(name)
        _part_dir, stl = _resolve_part(name)
        if stl is None or not Path(stl).is_file():
            raise HttpError(404, "part %r has no STL" % name)
        self._send(200, Path(stl).read_bytes(), "model/stl",
                   {"Content-Disposition": 'attachment; filename="%s.stl"' % name})

    # What a browser may download, and what to call it on the wire. An
    # allow-list rather than "whatever is in out/": this route takes an
    # extension from the URL, and the one thing it must never do is hand back
    # spec.yaml, model.py or anything else that happens to be sitting there.
    DOWNLOADABLE = {
        "stl": "model/stl",
        "step": "model/step",
        "3mf": "model/3mf",
        "png": "image/png",
    }

    #: The renders write_bundle leaves in a part's out/ directory, by the name
    #: a person would ask for rather than the filename.
    RENDERS = {
        "heightmap": "heightmap.png",
        "section": "section.png",
        "preview": "preview.png",
    }

    #: The only two places a part may live. Anything resolving outside these is
    #: refused rather than corrected - see _owned_directory.
    MANAGED_ROOTS = ("parts",)

    def _owned_directory(self, name: str) -> Path:
        """
        The directory this name refers to, PROVED to be one of ours.

        THIS GUARD IS THE WHOLE OF WHY DELETE IS SAFE. `_resolve_part` finds a
        directory by asking the library, and the library is a scan of two
        roots - so in practice it only ever returns something under parts/ or
        library/. "In practice" is not good enough for a call that removes a
        directory tree. The path is resolved and checked to be genuinely
        beneath a managed root, so a name that somehow escaped the scan, a
        symlink pointing elsewhere, or a future change to how parts are found
        cannot turn this into a recursive delete of somebody's home directory.
        """
        from whittle import imports

        self._check_name(name)
        part_dir, _stl = _resolve_part(name)
        resolved = Path(part_dir).resolve()

        roots = [Path(r).resolve() for r in self.MANAGED_ROOTS]
        roots.append(Path(imports.IMPORT_ROOT).resolve())
        for root in roots:
            if resolved != root and root in resolved.parents:
                return resolved

        raise HttpError(
            400, "%s is not inside a directory this server manages" % name)

    def _delete_part(self, name: str) -> dict:
        """
        Remove a part and everything in it. There is no undo.

        WHY THIS EXISTS AT ALL. A library you cannot remove anything from is a
        library that fills with failed attempts until finding the good one is
        the hard part - and on this engine most of what accumulates is drafts
        from runs that timed out. Rule 31's "no template fits" being the normal
        case means the normal case also leaves a lot behind.

        WHAT MAKES IT SAFE IS THE GUARD, NOT THE CONFIRMATION. A dialogue in
        the client is a courtesy; `_owned_directory` is the part that means a
        crafted name cannot reach outside parts/ or library/. The client asks
        first because deleting somebody's work by mistap is unforgivable, and
        the server refuses out-of-bounds because a client is not a security
        boundary.
        """
        import shutil

        directory = self._owned_directory(name)
        # WHAT IS ABOUT TO GO, counted before it goes, so the answer can say
        # what was actually removed rather than that something was.
        files = sum(1 for _ in directory.rglob("*") if _.is_file())
        shutil.rmtree(directory)
        return {"ok": True, "removed": str(directory), "files": files}

    def _rename_part(self, name: str, wanted: str) -> dict:
        """
        Give a part a different directory name.

        THE DIRECTORY IS THE PART'S IDENTITY - every route resolves by it, and
        a refinement writes `birdhouse_2` beside `birdhouse`, so a library of
        chains is a library of names nobody chose. Renaming is how "birdhouse_6"
        becomes "front garden box".

        THE SPEC'S OWN NAME IS NOT TOUCHED. It is what the part calls itself,
        it is recorded in run.json and regression.json, and rewriting it here
        would leave those disagreeing with the file they describe. The
        directory is the thing this renames, which is exactly the thing the
        clients navigate by.
        """
        if not SAFE_NAME.fullmatch(wanted or ""):
            raise HttpError(
                400, "%r is not a name a directory can have - letters, digits, "
                     "dot, dash and underscore" % wanted)

        directory = self._owned_directory(name)
        target = directory.parent / wanted
        if target.resolve() == directory:
            return {"ok": True, "dir": directory.name, "unchanged": True}

        # TAKEN ANYWHERE IN THE LIBRARY, NOT JUST IN THIS FOLDER.
        #
        # `target.exists()` asks whether the new path is free, and the library
        # is TWO roots: parts/ for what the engine builds, library/ for what
        # somebody brought in. So renaming a part to the name of an imported
        # model passed this check and produced two directories answering to
        # one name - after which `_resolve_part` picks whichever the scan
        # returns first, and a route that reads one and a route that deletes
        # the other are both doing what they were told.
        #
        # It cost a real part: a test renamed a throwaway onto an imported
        # mesh's name, and every later request for that name reached a
        # directory holding somebody else's spec.
        from whittle import imports

        roots = [Path(r) for r in self.MANAGED_ROOTS] + [Path(imports.IMPORT_ROOT)]
        clash = next((root / wanted for root in roots if (root / wanted).exists()), None)
        if clash is not None:
            raise HttpError(
                409, "there is already something called %r, in %s"
                     % (wanted, clash.parent))

        directory.rename(target)

        # THE NAME IS THE CACHE KEY'S NEIGHBOUR. A scan remembers directories
        # by path, and this one has just moved: saying so is cheaper than the
        # next request discovering an entry that no longer exists.
        from whittle import library as library_mod

        library_mod.forget(directory)
        library_mod.forget(target)

        return {"ok": True, "dir": target.name, "was": directory.name}

    def _send_render(self, name: str, kind: str):
        """
        One of a part's rendered images, INLINE, for a screen to draw.

        RULE 27 AND RULE 28 HAD NO ROUTE. "The height map is the primary
        geometry-verification visual, not the shaded render" - because a
        flat-shaded renderer cannot show a recess whose floor shares a normal
        with the surrounding face - and "no part is done until whittle verify
        passes and a height map has been generated and looked at".

        Every part on disk has one. Neither client could show it. The only way
        to reach a PNG was /api/part/<n>/file/png, which globs out/*.png, takes
        whichever sorts first, and serves it as an ATTACHMENT - so it happened
        to be the height map, by alphabet, offered as a download.

        A named kind and no Content-Disposition, so an <Image> can point at it.
        Cached like the frames: a built part's renders never change, because a
        refinement writes a new part.
        """
        self._check_name(name)
        filename = self.RENDERS.get(kind)
        if filename is None:
            raise HttpError(
                404, "%r is not a render - there is %s"
                     % (kind, ", ".join(sorted(self.RENDERS))))
        part_dir, _stl = _resolve_part(name)
        target = part_dir / "out" / filename
        if not target.is_file():
            # A REAL ANSWER, NOT A BLANK. A part built before this render was
            # written, or a draft with no mesh, genuinely has none - and a
            # screen that knows that can say so instead of drawing an empty box.
            raise HttpError(404, "%s has no %s render" % (name, kind))
        self._send(200, target.read_bytes(), "image/png",
                   {"Cache-Control": "public, max-age=604800, immutable"})

    def _send_file(self, name: str, ext: str):
        self._check_name(name)
        ctype = self.DOWNLOADABLE.get(ext)
        if ctype is None:
            raise HttpError(404, "%r is not a downloadable format" % ext)
        part_dir, _stl = _resolve_part(name)
        found = sorted((part_dir / "out").glob("*.%s" % ext))
        if not found:
            raise HttpError(404, "part %r has no %s file" % (name, ext.upper()))
        self._send(200, found[0].read_bytes(), ctype,
                   {"Content-Disposition": 'attachment; filename="%s.%s"' % (name, ext)})

    def _sse(self, job_id: str):
        job = JOBS.get(job_id)
        if job is None:
            raise HttpError(404, "no such job")

        backlog, q = job.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        def write(event: dict) -> bool:
            try:
                self.wfile.write(("data: %s\n\n" % json.dumps(event)).encode())
                self.wfile.flush()
                return True
            except (BrokenPipeError, ConnectionResetError):
                return False

        try:
            for event in backlog:
                if not write(event):
                    return
            if job.done:
                return
            while True:
                try:
                    event = q.get(timeout=15.0)
                except queue.Empty:
                    # A comment frame, so a proxy or a sleeping phone does not
                    # decide the connection is dead.
                    try:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    continue
                if not write(event):
                    return
                if event.get("kind") == "closed":
                    return
        finally:
            job.unsubscribe(q)
            self.close_connection = True


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    """
    Run the server until interrupted.

    The default binds to loopback, so nothing is exposed by accident. Pass
    0.0.0.0 to reach it from a phone on the same network - that is a deliberate
    act and it prints what it did, because a CAD tool quietly listening on
    every interface is not something anyone should discover later.
    """
    httpd = ThreadingHTTPServer((host, port), Handler)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("whittle is listening on ALL interfaces (%s:%d)." % (host, port))
        print("Anyone on this network can reach it. There is no password.")
        for addr in _local_addresses():
            print("  on your phone:  http://%s:%d" % (addr, port))
    else:
        print("whittle web:  http://%s:%d" % (host, port))
        print("  (loopback only - use --host 0.0.0.0 to reach it from a phone)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def _local_addresses() -> list[str]:
    """This machine's LAN addresses, so the phone URL can be printed."""
    import socket

    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 1))          # TEST-NET-1, never actually routed
        out.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return out or ["<this machine's IP>"]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Serve whittle to a browser.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    serve(args.host, args.port)
