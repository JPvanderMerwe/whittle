"""
Changing a part you have already built, by describing the change.

THE IDEA
--------
A refinement does not touch geometry. It edits the SPEC, and the spec is rebuilt
from scratch. So "make it 10 mm wider" is an exact parameter change followed by
a deterministic build, not a re-roll that might come back different in ways you
did not ask for.

That also means every turn leaves a complete, valid spec.yaml. The history is a
sequence of specs: diffable, revertible, and each one printable on its own.

WHY A DIFF RATHER THAN A WHOLE SPEC
-----------------------------------
The model is asked for ONLY the parameters that change. Asking a small model to
restate a specification it was not asked to change is asking it to make mistakes
in the parts it was supposed to leave alone - a value gets rounded, a field it
did not understand gets dropped, and the part quietly moves in a direction
nobody requested.
"""

from __future__ import annotations

from typing import Any, Callable

from whittle.agent import prompts
from whittle.agent.handoff import FieldProblem, problems_from_validation_error
from whittle.agent.loop import STAGE_PARSE, STAGE_VALIDATE, AskResult, SpecRejected
from whittle.models.selector import Attempt, Profile, run_ladder
from whittle.spec.schema import PartSpec


class CannotRefine(Exception):
    """
    The instruction asks for something no parameter can express.

    A correct answer, not a failure. Asked to "add a feeding area", a model with
    only dimensions to change made the birdhouse bigger - twice - and every
    check passed it, because a bigger birdhouse is a sound object. Saying so
    costs one attempt; approximating it costs a print.
    """


def apply_changes(spec: PartSpec, changes: dict[str, Any]) -> PartSpec:
    """
    Merge a parameter diff onto a spec, returning a new one.

    A null means "let this go back to being derived from the frame", which is
    how a refinement asks for the automatic behaviour it may have overridden
    earlier. Dropping the key entirely is what makes that work - the template's
    own derivation only runs for parameters that are absent.
    """
    params = dict(spec.params or {})
    for key, value in (changes or {}).items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value

    data = spec.model_dump(exclude_none=True)
    data["params"] = params
    return PartSpec.model_validate(data)


def validate_changes(
    spec: PartSpec, changes: dict[str, Any]
) -> tuple[PartSpec, list[FieldProblem]]:
    """
    Apply a diff and check the result, returning per-field problems rather than
    raising, so a refinement can be critiqued the same way a first attempt is.
    """
    from pydantic import ValidationError

    from whittle.build.compile import SpecError, validate_params

    try:
        merged = apply_changes(spec, changes)
    except ValidationError as exc:
        raise SpecRejected(
            "the change produced an invalid spec",
            stage=STAGE_VALIDATE,
            problems=problems_from_validation_error(exc),
        ) from exc

    if merged.level != 1 or not merged.template:
        return merged, []

    try:
        validate_params(merged)
    except SpecError as exc:
        problems: list[FieldProblem] = []
        from whittle.spec import registry

        try:
            registry.get(merged.template).params_model.model_validate(merged.params)
        except ValidationError as pexc:
            for p in problems_from_validation_error(pexc):
                p.field = "params.%s" % p.field
                problems.append(p)
        raise SpecRejected(
            str(exc), stage=STAGE_VALIDATE, problems=problems, data=merged.model_dump()
        ) from exc

    return merged, []


def apply_ops(spec: PartSpec, ops: list) -> PartSpec:
    """Replace a level-2 spec's operation list, returning a new spec."""
    data = spec.model_dump(exclude_none=True)
    data["ops"] = ops
    data["level"] = 2
    return PartSpec.model_validate(data)


def refine_ops(
    spec: PartSpec,
    instruction: str,
    profile: Profile,
    report: Any = None,
    on_attempt: Callable[[Attempt], None] | None = None,
    verify_fn: Callable[[PartSpec], Any] | None = None,
) -> AskResult:
    """
    Change a part built from primitives.

    JSON mode, not a schema: the operation list is a discriminated union and
    Ollama does not enforce those, so constraining it makes the model emit
    operations with no numbers. See models.ollama.JSON_ONLY.
    """
    from whittle.agent.loop import _hint
    from whittle.models.ollama import JSON_ONLY
    from whittle.spec.dsl import DslError, parse_op

    system = prompts.REFINE_OPS_SYSTEM
    base_user = prompts.build_refine_ops_prompt(spec, instruction, report=report)
    state: dict[str, Any] = {"user": base_user, "best": {}, "problems": [], "note": ""}

    def one_attempt(backend) -> PartSpec:
        raw = backend.complete(system, state["user"], JSON_ONLY)
        try:
            data = prompts.parse_reply(raw)
        except ValueError as exc:
            state["user"] = prompts.critique_prompt(
                raw, str(exc), '- send a single JSON object with an "ops" list'
            )
            raise SpecRejected(str(exc), stage=STAGE_PARSE, raw=raw) from exc

        ops = data.get("ops")
        if not isinstance(ops, list) or not ops:
            problem = 'the reply had no "ops" list. Send {"ops": [...]}.'
            state["user"] = prompts.critique_prompt(raw, problem, "- add an ops list")
            raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)

        state["best"] = {"ops": ops}
        state["note"] = data.get("note", "")

        for i, op in enumerate(ops):
            if not isinstance(op, dict):
                problem = "ops[%d] is not an object" % i
                state["user"] = prompts.critique_prompt(raw, problem, "- fix ops[%d]" % i)
                raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)
            try:
                parse_op(op)
            except DslError as exc:
                problem = "ops[%d] is invalid: %s" % (i, exc)
                state["user"] = prompts.critique_prompt(
                    raw, problem,
                    "- fix ops[%d]. %s" % (i, str(exc).split(chr(10))[0]),
                )
                raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw) from exc

        try:
            merged = apply_ops(spec, ops)
            if verify_fn is not None:
                verify_fn(merged)
        except SpecRejected as exc:
            exc.raw = raw
            state["problems"] = exc.problems
            state["user"] = prompts.critique_prompt(
                raw, str(exc), exc.hint or _hint(exc.problems)
            )
            raise
        state["problems"] = []
        return merged

    ladder = run_ladder(profile, one_attempt, on_attempt=on_attempt)
    result = AskResult(
        spec=ladder.value if ladder.ok else None, ladder=ladder,
        request=instruction, machine=profile.name,
        best_attempt_data=state["best"], problems=state["problems"], level=2,
    )
    result.note = state["note"]
    return result



def _decide_locally(
    spec: PartSpec,
    instruction: str,
    verify_fn: Callable[[PartSpec], Any] | None = None,
) -> AskResult | None:
    """
    Read the instruction against this template's own schema, with no model.

    Returns None when the sentence asks for something the parser cannot decide
    - which is when the model is worth the minutes it costs. Returns an
    AskResult with the spec already changed when it can, and that result is
    the same shape as the model's, so nothing downstream needs a second path.

    A sentence that maps to NOTHING is deliberately handed on rather than
    refused here: "make it look like a proper birdhouse" is beyond a parser and
    is exactly the kind of thing worth asking a model about.
    """
    if spec.level == 2 or not spec.template:
        return None

    try:
        from whittle.spec import language, registry

        template = registry.get(spec.template)
    except Exception:
        return None

    current = dict(spec.params or {})
    reading = language.read(instruction, template.params_model, current)
    if not reading.changes:
        return None

    # AMBIGUITY IS NOT DECIDED HERE. If the sentence could mean two fields, the
    # parser says so and the model gets its turn rather than a coin being
    # flipped on somebody's part.
    if reading.questions:
        return None

    changed = spec.model_copy(deep=True)
    changed.params = {**current, **reading.as_params()}

    try:
        template.params_model(**changed.params)
    except Exception:
        # The schema refused the combination - out of bounds, or a validator
        # that knows two fields cannot both be what was asked. That is a real
        # answer and the model may be able to find a legal way to do it.
        return None

    # BUILT AND VERIFIED, exactly as the model's answer would be. Skipping this
    # would return a spec nobody had built, and the caller - which expects a
    # part - would get None with no explanation. A parser is allowed to be
    # faster than the model; it is not allowed to be less checked.
    if verify_fn is not None:
        try:
            verify_fn(changed)
        except Exception:
            # The change is legal on paper and does not build. The model is
            # worth asking, because it can choose a different way to get there.
            return None

    note = "; ".join(c.describe() for c in reading.changes)
    if reading.unmapped:
        # RULE 32: what was not understood is said out loud, every time.
        note += " (nothing geometric in: %s)" % "; ".join(reading.unmapped)

    # AN EMPTY LADDER, NOT NO LADDER. A refinement decided without a model
    # genuinely made no attempts, and `ladder=None` would make every caller
    # that reports what was tried into a special case - api.refine reads
    # `.attempts`, `.never_reached_a_model` and `.last_error` off it. One
    # shape, one code path.
    from whittle.models.selector import LadderResult

    return AskResult(spec=changed, request=instruction, level=1, note=note,
                     ladder=LadderResult(ok=True, value=changed))


def _template_now_claims(spec: PartSpec, instruction: str) -> str | None:
    """
    A part built from primitives that a template WOULD make, if asked today.

    THE FAILURE THIS FIXES, IN THE OWNER'S WORDS: "i tried to reprompt the
    phone stand in the app... whittle has created an ugly block for the phone
    stand".

    He was right, and the reason was one line below: a level-2 part goes to
    refine_ops, which nudges the numbers of the primitives it already has.
    parts/phone_stand is a 100 x 100 x 30 rounded prism with a wedge cut out
    of it and a pocket in the top - a block with a slit in it - because it was
    built BEFORE there was a stand template. Reprompting it asked a model to
    make a better block. It could never become a stand, however many times
    anybody asked, because nothing in that path can change what a part is made
    of.

    That breaks the promise the whole product rests on. "Work it until it is
    right" is worth nothing if an object cannot escape the way it was first
    built.

    So a part with no template is offered to the router before it is sent to
    the operations path, and the router reads the part's OWN NAME as well as
    the instruction - "phone_stand" is what the person called it and is the
    best statement of what they wanted. If a template claims it now, the part
    is rebuilt as that template.

    NOTHING IS DESTROYED. A refine writes a new part and leaves the old one
    alone, which is what makes this safe to do at all.
    """
    if spec.template:
        return None
    try:
        from whittle.agent.route import route
    except Exception:
        return None

    # THE NAME AND THE INSTRUCTION TOGETHER. The name carries what the thing
    # is ("phone_stand"); the instruction usually carries only the change
    # ("make it look better"), which claims nothing on its own.
    said = "%s %s" % (str(getattr(spec, "name", "") or "").replace("_", " "),
                      instruction or "")
    decided = route(said)
    if not decided.template_road or not decided.matched:
        return None
    # The router sorts its matches longest phrase first, so the head is the
    # most specific claim anything made on this request.
    return decided.matched[0][1]


def _rebuild_as_template(
    spec: PartSpec,
    template_name: str,
    instruction: str,
    verify_fn: Callable[[PartSpec], Any] | None = None,
) -> AskResult | None:
    """
    Rebuild a primitives part as the template that now claims it.

    NO MODEL. The template's own defaults are a better starting point than
    anything a 7B model invents for a shape it has never been shown, and the
    instruction is then read against the template's schema by the same parser
    that handles every other sentence. Rule 11: this has to work with no model
    at all, and a part escaping a bad first build is exactly the case where
    nobody should have to wait two minutes for a GPU.

    Returns None if the template will not take it, and the caller falls back
    to the operations path - a worse answer, but a real one.
    """
    from whittle.models.selector import LadderResult
    from whittle.spec import language, registry

    try:
        template = registry.get(template_name)
    except Exception:
        return None

    changed = spec.model_copy(deep=True)
    changed.level = 1
    changed.template = template_name
    # AN EMPTY LIST, NOT None. `ops` is `list[dict]` with [] for a default, so
    # None is not a legal value for it - a spec carrying one passes model_copy,
    # which does not revalidate, and is then refused the next time anything
    # loads it back. A part that builds once and cannot be reopened is the
    # worst shape this could have taken.
    changed.ops = []
    changed.params = {}

    # The instruction, read against the template it is now about. Anything the
    # parser cannot place is reported rather than dropped - rule 32.
    unmapped: list[str] = []
    try:
        reading = language.read(instruction, template.params_model,
                                dict(template.params_model().model_dump()))
        changed.params = reading.as_params()
        unmapped = list(reading.unmapped)
    except Exception:
        changed.params = {}

    try:
        template.params_model(**changed.params)
    except Exception:
        return None

    if verify_fn is not None:
        try:
            verify_fn(changed)
        except Exception:
            return None

    note = (
        "rebuilt as the %s template. It was made from primitives, before "
        "there was a template for this - which is why it was a block. The "
        "older one is still in the library." % template_name
    )
    if changed.params:
        note += " Set from what you said: %s." % ", ".join(sorted(changed.params))
    if unmapped:
        note += " Nothing geometric in: %s." % "; ".join(unmapped)

    return AskResult(spec=changed, request=instruction, level=1, note=note,
                     ladder=LadderResult(ok=True, value=changed))


def refine(
    spec: PartSpec,
    instruction: str,
    profile: Profile,
    report: Any = None,
    measurements: dict[str, Any] | None = None,
    on_attempt: Callable[[Attempt], None] | None = None,
    verify_fn: Callable[[PartSpec], Any] | None = None,
) -> AskResult:
    """
    Ask the model to change one thing about an existing part.

    Returns the same AskResult shape as a first generation, so the caller does
    not need a second code path for "this was a refinement".
    """
    from whittle.agent.loop import _hint

    # THE PARSER GETS FIRST REFUSAL, AND THE MODEL ONLY SEES WHAT IT CANNOT DO.
    #
    # CLAUDE.md rule 32: English is the interface. Most of what people actually
    # type is a shape word or a dimension of the thing in front of them -
    # "make this roof a triangular roof" - and that is decidable without a
    # model, exactly as M3 decided it for the mesh operations.
    #
    # Doing it here rather than in the web route means every caller gets it:
    # the CLI, the phone, and the web client, with one implementation. And it
    # means an instruction the parser understands NEVER depends on a 7B model
    # being having a good day, which this repo has measured twice and written
    # down twice.
    decided = _decide_locally(spec, instruction, verify_fn)
    if decided is not None:
        return decided

    # A part built from primitives has no template and no params, so the
    # parameter-diff path has nothing to show the model.
    if spec.level == 2 or not spec.template:
        # BUT FIRST: DOES A TEMPLATE CLAIM IT NOW? A part built before its
        # template existed is stuck as primitives for ever otherwise - see
        # _template_now_claims for the phone stand that made this obvious.
        claimed = _template_now_claims(spec, instruction)
        if claimed:
            rebuilt = _rebuild_as_template(spec, claimed, instruction, verify_fn)
            if rebuilt is not None:
                return rebuilt

        # Send it to the operations path instead.
        return refine_ops(
            spec, instruction, profile, report=report,
            on_attempt=on_attempt, verify_fn=verify_fn,
        )

    system = prompts.REFINE_SYSTEM
    base_user = prompts.build_refine_prompt(
        spec, instruction, report=report, measurements=measurements
    )
    schema = prompts.refine_schema(spec.template or "")

    state: dict[str, Any] = {"user": base_user, "best": {}, "problems": [], "note": ""}

    def one_attempt(backend) -> PartSpec:
        raw = backend.complete(system, state["user"], schema)
        try:
            data = prompts.parse_reply(raw)
        except ValueError as exc:
            state["user"] = prompts.critique_prompt(
                raw, str(exc), "- send a single JSON object with a params field"
            )
            raise SpecRejected(str(exc), stage=STAGE_PARSE, raw=raw) from exc
        except CannotRefine as exc:
            state["cannot"] = str(exc)
            raise

        if data.get("cannot"):
            raise CannotRefine(
                "no parameter of this template can do that: %s"
                % str(data["cannot"])[:200]
            )

        changes = data.get("params")
        if not isinstance(changes, dict):
            problem = (
                "the reply had no `params` object. Send {\"params\": {...}} "
                "holding only the parameters that change."
            )
            state["user"] = prompts.critique_prompt(raw, problem, "- add a params object")
            raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)

        if not changes:
            problem = (
                "the reply changed nothing. If the instruction cannot be met by "
                "changing a parameter, change the closest one you can."
            )
            state["user"] = prompts.critique_prompt(raw, problem, "- change at least one parameter")
            raise SpecRejected(problem, stage=STAGE_VALIDATE, raw=raw)

        state["best"] = {"template": spec.template, "params": changes}
        state["note"] = data.get("note", "")

        try:
            merged, _ = validate_changes(spec, changes)
            if verify_fn is not None:
                verify_fn(merged)
        except SpecRejected as exc:
            exc.raw = raw
            state["problems"] = exc.problems
            state["user"] = prompts.critique_prompt(
                raw, str(exc), exc.hint or _hint(exc.problems)
            )
            raise
        state["problems"] = []
        return merged

    ladder = run_ladder(profile, one_attempt, on_attempt=on_attempt)

    result = AskResult(
        spec=ladder.value if ladder.ok else None,
        ladder=ladder,
        request=instruction,
        machine=profile.name,
        best_attempt_data=state["best"],
        problems=state["problems"],
        level=spec.level,
    )
    result.note = state["note"]           # what the model says it changed
    result.cannot = state.get("cannot", "")
    return result


def describe_op_changes(before: PartSpec, after: PartSpec) -> list[str]:
    """What changed in an operation list, read off the two specs."""
    old = [dict(o) for o in (before.ops or [])]
    new = [dict(o) for o in (after.ops or [])]
    out: list[str] = []

    old_names = [o.get("op") for o in old]
    new_names = [o.get("op") for o in new]
    for name in set(new_names) - set(old_names):
        out.append("added %s" % name)
    for name in set(old_names) - set(new_names):
        out.append("removed %s" % name)

    for i, (a, b) in enumerate(zip(old, new)):
        if a.get("op") != b.get("op"):
            out.append("op %d: %s -> %s" % (i, a.get("op"), b.get("op")))
            continue
        for key in sorted(set(a) | set(b)):
            if key == "op" or a.get(key) == b.get(key):
                continue
            out.append("%s.%s: %s -> %s" % (b.get("op"), key, a.get(key), b.get(key)))

    if len(new) != len(old):
        out.append("%d operations -> %d" % (len(old), len(new)))
    return out or ["no change to the operations"]


def describe_changes(before: PartSpec, after: PartSpec) -> list[str]:
    """
    What actually changed between two specs, in plain language.

    Read off the specs rather than taken from the model's word for it - a model
    that says it made something wider and did not is exactly the case worth
    catching, and it is invisible if the interface only ever repeats the claim.
    """
    if before.level == 2 or after.level == 2:
        return describe_op_changes(before, after)

    old = dict(before.params or {})
    new = dict(after.params or {})
    out: list[str] = []

    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a == b:
            continue
        if key not in new:
            out.append("%s: %s -> derived from the frame" % (key, a))
        elif key not in old:
            out.append("%s: derived -> %s" % (key, b))
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out.append("%s: %g -> %g (%+g)" % (key, a, b, b - a))
        else:
            out.append("%s: %s -> %s" % (key, a, b))

    for field in ("material", "nozzle_mm", "layer_mm", "print_axis"):
        a, b = getattr(before, field), getattr(after, field)
        if a != b:
            out.append("%s: %s -> %s" % (field, a, b))
    return out
