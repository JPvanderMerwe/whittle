# whittle — Build Plan v8

**Owner:** Bit Primitive Pty Ltd
**Date:** 11 September 2026
**Supersedes:** `whittle_build_plan_v7.md` entirely. v8 repositions the product: import-and-edit is the core, parametric generation is supporting infrastructure.
**Audience:** Claude Code, working in the existing whittle repo.

---

## 1. What whittle is

**whittle makes a mesh editable.**

Someone generates a dragon in Meshy, or downloads a bracket from Printables, or exports a scan. The file looks right and is useless as it stands — walls too thin, no flat base, too big for the bed, hollow in the wrong places, and completely frozen. There is nothing to adjust. Opening it in Blender means learning Blender.

whittle takes that file and lets the user change it by typing what they want.

**Positioning changed in this version.** We are not competing with Meshy. We are downstream of them. Meshy makes the shape; whittle makes it printable and changeable. Every model they generate is a potential whittle session, which means their marketing spend feeds us instead of fighting us.

**The one-line pitch:** finish what the generator started.

### What changed from v7

v7 led with parametric generation and treated import as an added capability. That was backwards. Most users will never generate parametrically — they arrive with a mesh and want to edit it.

So the order flips. Import, repair, print-prep and language-driven mesh editing become M1 to M4. The parametric engine, the family library and the mechanism system stay in the plan, but as infrastructure that powers specific features rather than as the headline.

---

## 2. The honest technical position

This section exists so nobody builds against a promise that cannot be kept.

**"Take a mesh and make it parametric" is not achievable in the general case.** A mesh is triangles. It has no features, no parameters, no design history. Recovering a feature tree from arbitrary triangles is an unsolved problem.

**And generator output is the hardest possible input for it.** Feature recognition works by finding flat planes and clean cylinders. Meshy output is organic and sculpted — curved everywhere, no flat faces, no cylinders, frequently non-manifold. The techniques that work on a CAD-exported bracket fail almost completely on a generated dragon.

So the product cannot be "mesh in, CAD model out."

**What it can be, and what is genuinely valuable:**

The mesh stays frozen. **Everything we do to it is parametric.** Every edit is an operation with named parameters, a slider, and an off switch. Scale is a number. Wall thickness is a number. Cut height is a number. Joint clearance is a number. The user gets adjustability over the edits even though the base geometry is fixed.

That is a real product, it is honest, and it is more than anyone else offers on generated meshes today.

Four toolkits, in order of reliability:

| Toolkit | Works on | Reliability |
|---|---|---|
| Print-prep (§6) | anything | High — pure mesh operations |
| Articulation (§8) | anything with a skeleton | High — we add the joints, we control them |
| Deformation (§7) | organic meshes | Medium — smooth and approximate, not exact |
| Feature editing (§9) | CAD-origin meshes and B-rep | High on CAD-origin, near-zero on generated |

Print-prep is the volume. Articulation is the moat. Deformation is the demo. Feature editing is for the functional-parts audience and should never be promised on generated meshes.

---

## 3. Non-goals

- Not a mesh-to-CAD converter. See §2.
- Not a sculpting tool. We do not compete with ZBrush or Blender on modelling.
- Not a slicer.
- Not simulation. We prove motion is geometrically possible. We do not compute torque, stress, load capacity, fatigue or spring force.
- Not a model marketplace.
- Not a texture-map product. Printable surface geometry only.
- Not a replacement for real CAD on precision work.

---

## 4. The architecture decision everything depends on

**The durable artefact is never baked geometry. It is a source plus an ordered stack of parameterised operations.**

```
ProjectSpec
  id                  uuid
  spec_version        int                   # start at 3
  origin              "import" | "generate"
  source              SourceFile | null     # the frozen base mesh
  generator           GeneratorSpec | null  # parametric script, when origin=generate
  edits               [EditOp]              # the stack, ordered
  articulation        MechanismGraph | null # when the object has been jointed
  shared_parameters   [Parameter]           # scale, wall_mm, clearance_mm, nozzle_mm
  export              ExportSpec

SourceFile
  filename, format, hash
  topology            "mesh" | "brep"
  triangle_count      int
  units               mm | cm | in | unknown
  repaired            bool
  repair_log          [str]
  provenance_hint     "meshy" | "printables" | "scan" | "cad" | "unknown"

EditOp
  id                  str
  kind                EditKind
  parameters          [Parameter]
  values              {name: value}
  enabled             bool                  # non-destructive toggle
  target              Selector | null
  cached_result_hash  str | null            # skip recompute when upstream unchanged

Selector
  mode                "all" | "segment" | "feature" | "region" | "index"
  segment_id          str | null            # from §7.1 segmentation
  feature_type        hole | boss | planar_face | cylinder | fillet | null
  filter              dict
  resolved_ids        [int]
```

The stack is evaluated in order, with caching keyed on upstream hashes so moving one slider does not recompute the whole chain. This caching is not an optimisation to add later — interactive editing is the product, and a stack that recomputes from scratch on every drag is not interactive.

---

## 5. Ingest

```
file
  ↓
[1] parse + format detect     stl · 3mf · obj · ply · glb · step · iges · brep
  ↓
[2] unit detection            STL carries no units; infer from bounding box, confirm with user
  ↓
[3] repair                    manifold, watertight, normals, duplicate verts, shell merge
  ↓                            log every change, show it, allow undo of repair itself
  ↓
[4] proxy decimation          keep full-resolution original; work on a proxy above ~300k tris
  ↓
[5] printability report       §10 gate, run immediately
  ↓
[6] analysis                  segmentation (§7.1), skeleton (§8.2), feature fit (§9)
  ↓                            all best-effort, all non-blocking, all cached
  ↓
[7] ready to edit
```

**Step 5 is the first impression and it is free value.** Before the user changes anything, tell them: this has 3 non-manifold edges, a 0.6mm wall that will not print on your 0.4mm nozzle, no flat base, and it is 40mm too tall for your bed. That report alone is worth the session, and it is what nobody gives them today.

**Format decides capability.** STEP, IGES and BREP carry real topology and unlock §9 fully. GLB and 3MF carry units and multi-body info that STL loses. STL, OBJ and PLY are triangle soup. Say so at upload — if the model page offered a STEP file, telling the user to grab that instead is useful advice that costs us nothing.

**Detect generator provenance where possible** (triangle density signature, watertightness, typical Meshy export naming). It lets the UI lead with the right toolkit: a generated organic mesh should surface print-prep and articulation first, not hole editing.

---

## 6. Print-prep — the volume

These are the operations generated meshes actually need. They work on any triangle soup, they never fail on organic geometry, and they are what turns an unusable download into a successful print.

`scale_uniform` · `scale_axis` · `rotate` · `auto_orient` (minimise supports, maximise bed contact) · `flatten_base` (cut a flat face so it stands) · `add_base` (add a plinth or raft-friendly foot) · `mirror` · `hollow` (offset inward to a wall thickness) · `thicken_thin_walls` (find sub-nozzle regions and inflate them locally) · `drain_holes` (for resin, or to let hollow parts vent) · `cut_plane` (split for bed fit, with dowel pins or dovetails auto-added at the cut face) · `split_bodies` · `merge_bodies` · `boolean_primitive` (add or subtract box, cylinder, sphere) · `emboss_text` · `engrave_text` · `add_loop` (keyring or hanging hole) · `smooth` · `decimate` · `repair` · `remove_floaters` (delete disconnected debris shells, which generated meshes are full of)

`thicken_thin_walls` and `remove_floaters` deserve attention. Both are near-universal problems in generated output and both are invisible until a print fails eight hours in. Solving them well is the clearest possible proof the product knows what it is doing.

Every one of these is parameterised. "Hollow it" produces a `wall_mm` slider the user drags from 1.2 to 2.4 and watches update live.

---

## 7. Deformation — editing organic shapes

This is how "make the tail longer" works on a Meshy dragon. It is approximate, not exact, and the UI should never imply otherwise.

### 7.1 Segmentation

Split the mesh into named parts so language has something to point at. Curvature-based region growing plus skeleton-informed splitting gets the common cases: head, body, limbs, tail, base. Label segments by size, position and skeletal role, then let the user rename them — user-supplied labels are more reliable than anything we infer, and renaming is one tap.

Segments become `Selector` targets. Cache them; recompute only when an upstream operation changes topology.

### 7.2 Operations

`deform_cage` — free-form deformation via a control lattice. Smooth, predictable, parameterised by cage point displacement.
`scale_segment` — lengthen, thicken or shrink one segment with falloff into its neighbours so it does not tear.
`bend_segment` — bend along the skeletal axis by an angle.
`taper_segment` · `twist_segment`
`smooth_segment` · `sharpen_segment`

Every one is a slider. "Make the tail longer" resolves to `scale_segment(tail, axis=length, factor=1.4)` and the user tunes `factor` from there without another inference call.

### 7.3 The honest limit

Deformation moves existing geometry. It cannot add detail that was never there, it cannot change a shape's identity, and heavy deformation will stretch surface detail visibly. Say this once, show a preview before committing, and never sell it as sculpting.

---

## 8. Articulation — the moat

**Take a static generated model and make it move.** Meshy produces a frozen dragon. whittle cuts it into segments, fits ball joints with correct print clearance, and exports it as a print-in-place articulated model that comes off the bed moving.

Nobody offers this. It is the single most compelling thing in the product, it is the demo video, and it is the reason someone pays.

### 8.1 Why it is tractable when parametric conversion is not

We are not recovering anything from the mesh. We are *adding* geometry we fully control. The joints are ours — we know their dimensions, their clearances and their ranges exactly. The mesh only has to be cut in the right places and have sockets booleaned into it.

That is why this works on organic generated meshes where feature recognition fails completely.

### 8.2 Pipeline

```
mesh
  ↓
[1] skeleton extraction       medial axis / mean curvature skeleton
  ↓
[2] segment proposal          cut planes perpendicular to the skeleton at joint candidates
  ↓                            user adjusts count and positions with a slider
  ↓
[3] joint fitting             ball-and-socket sized to local cross-section
  ↓
[4] boolean                   cut each segment, add ball to one side, socket to the other
  ↓
[5] clearance application     global clearance_mm applied to every socket
  ↓
[6] validation                §10 gate plus clearance gap check, bridging check, motion sweep
  ↓
[7] export                    in-place, assembled at rest
```

### 8.3 Clearance is the whole game

Too tight and the joints fuse during printing. Too loose and the model flops. Typical FDM working range is 0.2mm to 0.4mm depending on printer, material and nozzle.

`clearance_mm` is a **global shared parameter**, one slider labelled "Fit," and every joint derives its gap from it. Ship printer presets, and let the user calibrate once with a test print and keep the value.

**This is the feature no competitor can match.** One slider retunes every joint in the model at once.

### 8.4 Motion validation

Sweep every joint through its range in steps and check for collision at each step. This is the automated-sweep approach that already caught the crank sign error, the detached flange, the buried knob and the layer-height misalignment on the louvre vent. Same pattern, applied to imported geometry.

Report with the angle: "Segment 7 collides with segment 8 at 34°. Reduce the segment count or increase the gap."

### 8.5 Joint types

Ball-and-socket for organic articulation is the default and covers most cases. Beyond it: `revolute` (pin and sleeve, for hinged objects), `living_hinge` (thin web, material-dependent), `snap_fit`, `free` (nested, no constraint).

The full kinematic primitive set and mechanism graph from v6 remain in the plan for generated mechanisms — see §11 — but articulation of imported meshes needs only this subset, and it ships first.

---

## 9. Feature editing — for CAD-origin files

For imports that came from real CAD: brackets, mounts, enclosures, downloaded functional parts.

Segment by normal-based region growing, then fit primitives with RANSAC — planes, cylinders, spheres, cones, tori. Classify into through-holes, blind holes, bosses, planar faces, fillets, edge loops.

Operations: `resize_hole` · `move_hole` · `add_hole` · `pattern_hole` · `change_hole_to_thread` · `offset_face` · `resize_boss` · `edit_fillet_radius` · `add_counterbore` · `add_countersink`

"Make the mounting holes M4 instead of M3" is the most requested edit in functional printing and it lives here.

**On B-rep input (STEP, IGES, BREP) this is exact and reliable.** On CAD-origin STL it is good. **On generated organic meshes it does not work**, and the UI must not offer it there.

**Always show what was selected before applying.** Highlight the four holes and ask. A wrong selection silently applied is worse than no feature recognition at all.

---

## 10. The printability gate

Runs at ingest, on every operation, and on every parameter change where `affects_print` is true.

**Geometry:** manifold · watertight · no self-intersections · no zero-thickness or degenerate faces · no disconnected debris shells · body count matches the spec.

**Print:**
- Minimum wall thickness ≥ 2 × nozzle diameter (default 0.4mm nozzle → 0.8mm floor)
- Minimum feature size ≥ nozzle diameter. Detail finer than the nozzle prints as a smooth surface: an eight-hour print that comes out blank.
- Hollow wall thickness > minimum, and hollow cavities vented
- Overhang angle ≤ 45° unsupported — flagged, not blocked, with an auto-orient suggestion
- Bounding box within bed size (default 220 × 220 × 250, user-settable), with a `cut_plane` suggestion when it fails
- Flat base present, or `flatten_base` suggested
- Triangle count cap with adaptive decimation
- For articulated models: clearance gap check per joint pair, bridging check inside sockets, motion sweep

**On failure:** clamp slider ranges so most failures become impossible rather than reported. A slider the user cannot drag into a broken state beats an error message every time. Where a check still fails, name the violated rule and the responsible parameter: "Wall thickness 0.6mm is below the 0.8mm minimum for a 0.4mm nozzle. Increase to 0.8mm or thicker."

---

## 11. Parametric generation — now supporting infrastructure

Still in the product, no longer the headline. It serves three purposes:

**Geometry for articulation.** Joints, pins, sockets and cut features are generated parametrically. §8 depends on this.

**`fit_to_family`.** Where an import closely matches a known family silhouette, fit parameters and offer a fully parametric rebuild. When it works, the object becomes completely editable. Offer it only on confident matches and never imply it works generally.

**Generation from scratch** for users who want it: the family library, the surface pattern system, the mechanism graph with Kutzbach DOF validation and loop-closure solving, and free-form CadQuery synthesis with bounded retries. All of this is specified in v6 §5 to §7 and carries forward unchanged. It moves to M7 and later.

The family library also remains the SEO surface — one indexable page per family with a working generator — but import landing pages ("fix a Meshy model for printing", "make a downloaded STL fit your bed", "turn any model into an articulated print") are now the primary content play, because they match what people actually search for.

---

## 12. Language layer

Intent extraction produces an operation, never geometry:

```json
{
  "operation": "articulate",
  "selector": {"mode": "all"},
  "parameters": {"segments": 14, "joint": "ball"},
  "confidence": 0.91,
  "unmapped": ["make it look fierce"]
}
```

Rules:

- **Every edit becomes a parameter, not a one-shot.** After "hollow it," a `wall_mm` slider appears and the user tunes without further inference. This is the cost model as much as the UX.
- **Show the selection before applying it**, highlighted in the viewport.
- **`unmapped` surfaces every time.** "Make it look fierce" is not a geometric operation and pretending otherwise is how trust dies.
- **Ambiguity asks once**, with options highlighted in the viewport, not as a dialog.
- **Offer the operation the user actually needs.** If they say "make it stronger," respond with the real options: thicken walls, reduce hollow, add fillets, reorient for layer direction.

---

## 13. UI and experience

Meshy-level polish in whittle's own voice. The identity is established; do not redesign it.

### 13.1 Tokens

```
--bp-void        #0B0F0D   background
--bp-amber       #FFB000   primary accent, phosphor
--bp-amber-dim   #A67200   inactive, gridlines
--bp-paper       #E8E4D9   primary text
--bp-cut         #FF5C4D   error, violated constraint, collision, thin wall
--bp-datum       #4DA3FF   measurements, selected features and segments
--bp-motion      #6EE7A8   joints, motion paths
```

Type: one monospace family throughout — the CAD terminal is the identity. A second geometric sans for long-form marketing copy only, never inside the app UI.

### 13.2 Layout

```
┌──────────────────────────────────────────────────────────┐
│  viewport                                  │  edits      │
│                                            │             │
│      [mesh, plotter-line rendering,        │  ▣ repair   │
│       thin walls flagged in cut red]       │  ▣ hollow   │
│                                            │     wall ●──│
│      [segments in datum blue on hover]     │  ▣ articul. │
│                                            │     segs ──●│
│      ◁ ──────●────── ▶  motion             │     fit  ●──│
│                                            │             │
├────────────────────────────────────────────┤  [Export]   │
│ > make it hollow and cut it to fit my bed  │             │
└──────────────────────────────────────────────────────────┘
```

The **edit stack is the right rail** — ordered, each row toggleable, each expanding to its sliders. This replaces the parameter rail as the primary surface, because most sessions are imports.

Motion scrubber appears once a model is articulated.

### 13.3 Interaction rules

- **Slider drag re-renders live.** No inference call, no spinner. Cached stack evaluation makes this possible; without it the product does not work.
- **The printability report is always visible**, as a small persistent status, not a modal. Green when clean, `--bp-cut` with a count when not, expandable to the list.
- **Problems are shown on the model**, not described in text. Thin walls glow red in the viewport. Floaters get outlined. The overhang preview shades unsupported faces.
- **Every language edit shows a parameter diff**: `wall_mm 1.2 → 2.0`.
- **Operations are never destructive.** Toggle any row off and the model reverts through that step.
- **One orchestrated motion moment**: the boot sequence. Everything else responds to user action.

### 13.4 Things to avoid

Amber-on-dark monospace sits near some well-worn defaults. Stay specific to drafting and plotting rather than generic terminal chrome. No all-caps tracked-out eyebrow labels. No `→` on buttons. No identical rounded cards with identical soft shadows. No middle-dot meta strings. Gridlines, datum marks, dimension leaders and section hatching are the decorative vocabulary, and each must encode real information.

Spend the boldness on the viewport. Keep the rail quiet.

### 13.5 Copy

Active voice, sentence case, plain verbs. Buttons say what happens: "Export STL," not "Submit." Errors state what happened and what to do, never apologise, never go vague. The import drop zone is the main empty state — it should say what a good file looks like and accept a drag from a Meshy download folder without ceremony.

---

## 14. Milestones

**M1 — Ingest and report.** Parse all formats, unit detection, repair with log, proxy decimation, printability gate, CLI only. *Done when:* a Meshy GLB and a Printables STL both load, repair cleanly, and produce an accurate problem list.

**M2 — Print-prep operations.** The full §6 set, the edit stack with caching, non-destructive toggles. CLI. *Done when:* a generated dragon can be hollowed, flattened, thin-wall-thickened, de-floatered and cut for bed fit, and every operation stays adjustable afterwards.

**M3 — Language layer.** Intent to operation, selection confirmation, `unmapped` surfacing, parameter diffs. *Done when:* "hollow it to 2mm and cut it to fit my bed" produces the right two operations, ten times out of ten.

**M4 — UI.** Web app to §13. Live slider re-render, edit stack rail, problems shown on the model, export. *Done when:* dragging a wall thickness slider updates the viewport with no perceptible delay.

**This is the shippable product.** Import a generated mesh, make it printable, keep everything adjustable. Ship it before building anything below.

**M5 — Articulation.** Skeleton extraction, segment proposal, ball-socket fitting, global clearance, motion sweep, motion scrubber. *Done when:* a Meshy dragon exports as a print-in-place articulated model that moves off the bed, and one Fit slider retunes every joint.

**M6 — Segmentation and deformation.** §7 in full.

**M7 — Feature editing.** §9, plus the B-rep path for STEP input.

**M8 — Parametric generation core.** `GeneratorSpec`, family library, surface patterns, `fit_to_family`.

**M9 — Mechanism graph.** Kinematic primitives, DOF validation, loop-closure solver, mechanism presets.

**M10 — Mesh generation backend.** `MeshBackend` protocol, `LocalHunyuanBackend` at INT8 on the 3060 Ti, feeding the ingest pipeline at step 3. Note: Tencent's published requirements for Hunyuan3D-2.1 are 10GB VRAM for shape, 21GB for texture, 29GB for both, so the full pipeline does not fit an 8GB card. The INT8 quantised Shape 2.1 build, geometry only, does — and texture is discarded by slicers anyway. The home PC is a development target, not a serving target.

**M11 — Hosted backend, accounts, credit packs, mobile client.**

---

## 15. On sequencing

M5 is the moat and it will be tempting to build first. Don't. Articulation booleans sockets into segmented meshes, which requires repair, segmentation and the printability gate to be solid. Building it on an untested ingest pipeline means debugging joint clearance and mesh repair simultaneously.

M1 to M4 is narrow and shippable: bring a generated mesh, make it printable, keep it adjustable. That is already a product nobody else sells. M5 is what makes it one people talk about.

---

## 16. Open blockers — answer before M4

1. Flutter or React Native for the native client
2. Upload size ceiling — a 200MB scan is a very different cost profile from a 2MB bracket
3. Payment processing from a South African entity, given App Store and Play Store commission rules on digital goods
4. Whether developer accounts for both stores are registered under Bit Primitive Pty Ltd
5. Whether the current repo structure can serve two clients from one API
6. Where mesh processing runs at launch — browser WASM for small files keeps cost near zero, server-side handles everything but costs per session

None block M1 to M3.

---

## 17. Rules for this repo

- Follow existing patterns exactly; study the codebase first.
- Change only what is asked. No adjacent edits.
- Complete file rebuilds, not patches.
- Never push, commit or deploy without the literal word "push".
- Back up before risky steps.
- Open every response with `UNDERSTOOD / CHANGED / NOT CHANGED / BLOCKERS`.
