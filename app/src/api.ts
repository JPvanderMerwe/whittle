/**
 * The whittle server, as the app sees it.
 *
 * ONE CLIENT PER API, AND THE TYPES COME FROM THE SERVER'S ACTUAL PAYLOADS.
 * Everything here was written against whittle/web/server.py and
 * whittle/web/projects.py rather than from memory, which is why the shapes look
 * the way they do - `report.findings` really is failures and warnings
 * concatenated with a `severity` on each, and `units.alternatives` really is
 * the other readings of the same file with the size each would give.
 *
 * WHERE THE SERVER IS
 * -------------------
 * Loopback by default, because of `adb reverse tcp:8765 tcp:8765`. The phone's
 * own localhost is forwarded to the machine running `whittle web`, which needs
 * no LAN address typed into the app, survives the laptop changing networks,
 * and does not put the engine on the network for anyone else to reach.
 *
 * THE ADDRESS IS NO LONGER A CONSTANT, and that is the one thing that changed
 * here. It was baked in, so a phone that was not plugged in could not be made
 * to work at all - the app had a "not connected" screen with instructions and
 * no way to act on them. It is now built from the saved settings, which is why
 * `base` is a constructor argument and why the app makes its own Api rather
 * than importing a singleton.
 *
 * A device that is not plugged in and has no address set has no route, and the
 * Machine screen says so in those terms rather than showing a spinner for ever.
 */

import { LOOPBACK } from './address';

/** How long a call may take before the app says the machine is not answering. */
const TIMEOUTS = {
  /** Health, payloads, adding an op: all cheap on the server. */
  quick: 8000,
  /** An upload runs ingest - repair, gate, thickness - on arrival. */
  upload: 180000,
  /** A slider move rebuilds one step of the stack from the cache. */
  edit: 60000,
  /** The preview GLB, measured at 3 ms server-side plus the wire. */
  preview: 30000,
} as const;

export interface Finding {
  severity: string;
  rule: string;
  detail: string;
  fix: string;
  value: unknown;
}

export interface Report {
  printable: boolean;
  findings: Finding[];
  measurements: Record<string, unknown>;
  /** True while a slider is mid-drag: the geometry moved, the verdict has not. */
  stale?: boolean;
}

export interface Parameter {
  name: string;
  value: number | string | boolean;
  kind: string;
  units: string;
  low: number | null;
  high: number | null;
  choices: string[];
  slidable: boolean;
  description: string;
}

export interface Edit {
  id: string;
  kind: string;
  enabled: boolean;
  summary: string;
  parameters: Parameter[];
}

export interface Units {
  units: string;
  assumed: boolean;
  reason: string;
  alternatives: { units: string; size_mm: number }[];
}

export interface Repair {
  changed: boolean;
  steps: string[];
  unresolved: string[];
}

export interface Project {
  id: string;
  name: string;
  format: string;
  units: Units;
  repair: Repair;
  size_mm: [number, number, number];
  triangles: number;
  bodies: number;
  edits: Edit[];
  report: Report;
}

export interface CatalogueParameter {
  name: string;
  default: number | string | boolean;
  kind: string;
  units: string;
  low: number | null;
  high: number | null;
  choices: string[];
  description: string;
  affects_print: boolean;
  dynamic: boolean;
}

export interface CatalogueEntry {
  kind: string;
  summary: string;
  affects_print: boolean;
  parameters: CatalogueParameter[];
}

export interface Catalogue {
  operations: CatalogueEntry[];
  not_built_yet: string[];
}

export interface Said {
  echo: string;
  unmapped: string[];
  questions: { about: string; prompt: string; options: string[] }[];
  applied: { id: string; kind: string; derived: Record<string, string> }[];
  project: Project;
}


// ---------------------------------------------------------------------------
// making something from a sentence
// ---------------------------------------------------------------------------

/**
 * WHY THESE LIVE BESIDE THE IMPORT TYPES. whittle has two ways in and they are
 * equal: describe a part and the engine builds it, or bring a mesh and edit
 * it. Build plan v8 leads with import because that was the half that did not
 * exist; it never replaced the other half, and rule 31 is explicit that a
 * template is an optimisation rather than the boundary of the product.
 */

export interface LibraryPart {
  name: string;
  dir: string;
  template: string | null;
  prompt: string | null;
  makes: string[];
  size_mm: number[] | null;
  volume_cm3: number | null;
  bodies: number | null;
  material: string | null;
  level: number | null;
  when: string;
  built: boolean;
  /**
   * Where it came from, and it decides what can be done to it.
   *
   * 'built'    made here from a spec, so a sentence can rebuild it
   * 'imported' somebody else's triangles - hollow, cut and scale it as a mesh,
   *            but there is no parametric model to describe into a new shape
   *
   * Optional because an engine one version behind does not send it, and then
   * everything is treated as built - which is what that engine could do.
   */
  origin?: 'built' | 'imported';
  /** For an import: what the file was called when it arrived. */
  source_name?: string;
  note?: string;
  tags?: string[];
  /**
   * How many builds this tile stands for.
   *
   * A refine writes a NEW part and leaves the old one alone, so four tweaks
   * to a birdhouse are four directories all called "birdhouse". The engine
   * collapses a chain to its latest build and this is the count behind it -
   * 1 for anything standing only for itself.
   */
  builds?: number;
}

/**
 * What this machine has actually spent, measured off disk.
 *
 * EVERY FIGURE IS A SUM OVER RUNS THAT HAPPENED. run.json records each attempt
 * with the model that served it and the tokens in and out, so nothing here is
 * a counter somebody incremented - which is what makes it worth showing on a
 * screen about what things cost.
 *
 * There is no balance and no plan, because building here costs nothing per
 * part: the model is local, the geometry is local. A "tokens remaining" needs
 * a hosted service to be remaining FROM, and inventing one would be the exact
 * thing rule 29 forbids.
 */
export interface Usage {
  runs: number;
  built: number;
  drafts: number;
  model_calls: number;
  prompt_tokens: number;
  generated_tokens: number;
  tokens: number;
  machine_seconds: number;
  models: { name: string; attempts: number }[];
  first_run_at: number | null;
  last_run_at: number | null;
  /** False while everything runs locally. The server decides, not the client. */
  billable: boolean;
  why_free: string;
}

/** What a gallery asks the engine for. Every field is optional. */
export interface LibraryQuery {
  /** Free text, matched by the engine against everything that names a part. */
  q?: string;
  /** Which kinds to show. The words are the library's, not the schema's. */
  show?: 'all' | 'made' | 'brought-in' | 'unfinished';
  sort?: 'newest' | 'oldest' | 'name' | 'biggest' | 'smallest';
  material?: string;
  tag?: string;
  /** Ask for a page. Left out, the whole library comes back as it always did. */
  limit?: number;
  /** `next_cursor` from the page before. */
  cursor?: string;
  /**
   * 'latest' (the default) shows one tile per thing; 'all' shows every build.
   *
   * Collapsed on the ENGINE because the client no longer holds the whole
   * library - it holds a page, and a chain straddling a page boundary would
   * collapse differently depending on where the page fell.
   */
  builds?: 'latest' | 'all';
}

/**
 * One page of the library, and the counts that make it navigable.
 *
 * `total` is the whole library and `matched` is what the query found, which
 * is the difference between "0 of 412" and a gallery that looks empty.
 * `facets` counts what sits behind each filter over everything, so a chip can
 * say "brought in 318" rather than being a possibly-empty dead end.
 */
export interface LibraryAnswer {
  parts: LibraryPart[];
  total: number;
  matched: number;
  offset: number;
  limit: number | null;
  next_cursor: string | null;
  sort: string;
  show: string;
  facets: {
    show: { made: number; 'brought-in': number; unfinished: number };
    material: { name: string; count: number }[];
    tag: { name: string; count: number }[];
  };
}

/**
 * What a slicer said, or why it could not say it.
 *
 * TIME AND FILAMENT COME FROM A SLICER OR NOT AT ALL. They depend on walls,
 * infill and speed, which are not properties of the mesh - so whittle asks
 * a slicer and reports what it said, naming it. `evidence` is the comment
 * lines the figures were read out of, so a number on screen can be chased
 * back into the file.
 */
export interface SlicerSaid {
  available: boolean;
  ok?: boolean;
  /** The slicer's name and version, so the figures can be attributed. */
  name?: string;
  seconds?: number | null;
  grams?: number | null;
  filament_mm?: number | null;
  filament_cm3?: number | null;
  /** Null when the material has no density recorded - then there is no weight. */
  density_g_cm3?: number | null;
  density_source?: string;
  layers?: number | null;
  why?: string;
  evidence?: string[];
}

/** Everything known about printing one part. */
export interface PrintFacts {
  name: string;
  /** False for a draft: nothing was built, so there is nothing to print. */
  ready: boolean;
  why_not?: string;
  size_mm?: number[];
  bed_mm?: number[];
  /** Room left in each direction. Negative is how much too big it is. */
  spare_mm?: number[];
  fits?: boolean;
  printer?: string;
  /** Whether that bed was measured or is a published maximum. */
  bed_source?: string;
  layers?: number | null;
  layer_mm?: number;
  nozzle_mm?: number;
  material?: string | null;
  bodies?: number | null;
  volume_cm3?: number | null;
  watertight?: boolean | null;
  supports_needed?: boolean;
  unsupported_mm2?: number;
  bed_contact_mm2?: number;
  steepest_deg?: number;
  verdict?: string | null;
  files?: string[];
  for_the_slicer?: string;
  slicer?: SlicerSaid;
}

export interface PrintersAnswer {
  printers: {
    key: string;
    name: string;
    bed_mm: number[];
    nozzle_mm: number;
    source: string;
    /** True only for a bed somebody put a tape on. The rest are published. */
    measured: boolean;
  }[];
  using: { name: string; bed_mm: number[]; nozzle_mm: number };
  materials: string[];
}

/** One thing the engine said while it was working. */
export interface JobEvent {
  kind: string;
  at: number;
  text?: string;
  [key: string]: unknown;
}

export interface JobState {
  id: string;
  done: boolean;
  result: BuiltPart | { ok: false; message: string; attempts?: number } | null;
  events: JobEvent[];
}

/**
 * One job as the machine's own readout sees it - /api/jobs.
 *
 * THIS IS WHAT MAKES "YOU CAN LEAVE IT RUNNING" CHECKABLE. A build outlives
 * the screen that started it, which is a promise the app makes on the Making
 * screen; until this was read there was no way to ask what became of a build
 * whose screen had been left. The elapsed time is the server's own clock, and
 * the note is the last thing the engine actually said.
 */
export interface MachineJob {
  id: string;
  kind: string;
  request: string;
  done: boolean;
  ok: boolean;
  note: string;
  name: string;
  message: string;
  started_at: number;
  elapsed_s: number;
}

/**
 * A number the build CHOSE rather than was given. CLAUDE.md rule 14.
 *
 * THIS IS WHAT AN ORDINARY REQUEST PRODUCES. Nobody types "a bracket for a
 * 35 mm pipe, 4 mm thick, two M4 holes 60 mm apart" - they type "a bracket".
 * Every number in the result is therefore one of these, each with the reason
 * it had to be chosen, and the list IS what there is to change afterwards.
 *
 * It arrives as four fields rather than one sentence because a screen has to
 * offer changing ONE of them: the name reaches the template's schema and the
 * value is what a person is deciding about. The server used to send
 * `str(assumption)`, which welded all four into a Pydantic repr.
 */
export interface Assumption {
  /** The parameter this stands in for - the name the schema uses. */
  name: string;
  value: number | string;
  units: string;
  /** Why it could not be measured. Required by the model; never empty. */
  why: string;
}

/** An alternative the engine built by walking the spec's own axes. */
export interface PartOption {
  name: string;
  label: string;
  verdict: string;
  volume_cm3: number | null;
  envelope_mm: number[] | null;
}

export interface BuiltPart {
  ok: boolean;
  /** The spec's name, which is what a person reads. Not unique. */
  name: string;
  /**
   * The part's directory, which IS unique and is what every route resolves.
   *
   * A refinement keeps the spec name, so refining "birdhouse" writes
   * birdhouse_2 and calls itself "birdhouse". Navigating by `name` opened the
   * ORIGINAL and showed the unchanged part back to somebody who had just
   * asked to change it.
   */
  dir?: string;
  verdict: string;
  size_mm: number[] | null;
  volume_cm3: number | null;
  bodies: number | null;
  watertight: boolean | null;
  level: number | null;
  template: string | null;
  material: string | null;
  problems: string[];
  warnings: string[];
  notes: string[];
  assumptions: Assumption[];
  /**
   * Its own numbers, for a part built from operations rather than a template.
   *
   * SENT ON THE BUILD RESULT AS WELL AS ON /api/part, because this is what a
   * screen shows the moment a build finishes - reading them only off disk
   * would put the controls a screen late, which is exactly when somebody
   * wants to move them. Empty for a template part: those come from the
   * template's own schema.
   */
  dimensions?: ServedDimension[];
  report_md: string;
  files: string[];
  options?: PartOption[];
  elapsed_s?: number;
  attempts?: number;
}

/**
 * One measured line of a verify report.
 *
 * A LINE IS A MEASURED VALUE AND A STATUS, never a status alone - the server
 * builds these in `_checks_from_report` and its reason is worth repeating:
 * "watertight yes" and "worst overhang 12.4 deg" are what make this a report
 * rather than a green tick. `info` is a real status, not a cop-out: the number
 * of separate bodies decides whether a hinge turns and is neither pass nor
 * fail.
 */
export interface CheckLine {
  name: string;
  value: string;
  status: 'pass' | 'warn' | 'fail' | 'info';
}

export interface Checks {
  verdict: string;
  ok: boolean;
  problems: string[];
  warnings: string[];
  nozzle_mm: number | null;
  material: string | null;
  print_axis: string | null;
  lines: CheckLine[];
  /** 'stored' for the verdict it was built with, 'just now' for a re-check. */
  source: string;
  checked_at: number;
  /**
   * What has moved under a stored verdict since it was taken - a nozzle
   * change, a profile that will not load. Empty for a fresh check.
   */
  drift: string[];
}

/** Why a part never built, in the engine's own words. See `_draft_payload`. */
export interface Draft {
  request: string;
  attempts: number;
  elapsed_s: number;
  machine: string;
  models: string[];
  level_reached: number | null;
  /** The LAST error - the one the run gave up on. */
  message: string;
  handoff: string;
  spec_draft: string;
}

/**
 * A part read off disk, which is richer than the library card and richer than
 * the app has ever shown.
 *
 * `checks`, `draft`, `has_stl` and `files` were all being served and all being
 * thrown away: the screen read `checks.verdict` and nothing else, so a part
 * whose every measurement was on disk displayed as a name and a size.
 */
/**
 * One number of an ops spec as the SERVER describes it.
 *
 * Deliberately not the client's own `Dimension`: that type is what a slider
 * takes, with a label and units already resolved, and this is a payload. The
 * mapping between them is `dimensionsFromOps` in tweaks.ts, which is also
 * where the template's own parameters become the same thing.
 */
export interface ServedDimension {
  /** The address to send back: "0.width_mm", "1.step.diameter_mm". */
  name: string;
  label: string;
  value: number;
  /** Draggable ends, scaled off the value so the control can pick a number. */
  low: number;
  high: number;
  /** The limits the build actually enforces, off the op's own schema. */
  bound_low: number;
  bound_high: number;
  units: string | null;
  whole: boolean;
  description: string | null;
}

export interface PartDetail {
  name: string;
  dir: string;
  frames: number;
  spec?: Record<string, unknown>;
  level?: number | null;
  template?: string | null;
  material?: string | null;
  report_md?: string;
  size_mm?: number[];
  volume_cm3?: number;
  bodies?: number;
  checks?: Checks;
  draft?: Draft;
  /**
   * What this part assumed, off disk.
   *
   * Empty for anything built before run.json recorded them, which is a true
   * "none recorded" rather than a claim that none were made.
   */
  assumptions?: Assumption[];
  /**
   * The numbers of an OPS spec, ready to put sliders on.
   *
   * WHY THE SERVER SENDS THESE AND NOT THE TEMPLATE'S. A template part's
   * controls are built here, from the parameter schema this client fetches by
   * name. An ops spec has no template and no parameter names - its numbers
   * live at positions in a list, `ops[1].diameter_mm`, and their bounds are
   * on the op models in Python. A second copy of the DSL's schema in
   * TypeScript would drift the first time an op gained a field, so the server
   * reads the bounds it owns and sends the list.
   *
   * `name` is the address to send back: "0.width_mm", or "1.step.diameter_mm"
   * for the shape a pattern repeats. `low`/`high` are draggable ends scaled
   * off the value; `bound_low`/`bound_high` are the real limits the build
   * enforces.
   */
  dimensions?: ServedDimension[];
  has_stl: boolean;
  /** The extensions actually on disk: stl, step, 3mf, png. */
  files: string[];

  /**
   * Where it came from, and it decides what this screen may offer.
   *
   * An import has no spec, so there is nothing for a sentence to change and no
   * schema to put sliders on. Offering either is offering a control that
   * cannot work.
   */
  origin?: 'built' | 'imported';
  /** For an import: what the file was called when it arrived. */
  source_name?: string;
  note?: string;
  tags?: string[];
  triangles?: number;
  watertight?: boolean;
  /**
   * Why the importer could not fit it to a template, in its own words.
   *
   * "not a turned shape: cross-sections vary by 52.7% around the axis, so this
   * is not a turned shape - fitting a bowl to it would produce a confident
   * wrong answer." That sentence is the whole explanation for why this part
   * gets mesh operations instead of dimensions, and it was being discarded.
   */
  fit_note?: string;
}

export interface TemplateParameter {
  name: string;
  /** 'choice' when `choices` is non-empty, otherwise the Python type name. */
  type: string;
  /**
   * Every value a Literal field accepts, or [] for anything else.
   *
   * This was missing and the `type` was wrong: a Literal's arguments are
   * VALUES, so `roof_style: Literal["flat", "mono", "gable"]` reported its
   * type as "flat" and carried no other option anywhere. The one field a
   * person is most likely to change described itself as one of its own
   * answers.
   */
  choices: string[];
  optional: boolean;
  required: boolean;
  default: unknown;
  bounds: Record<string, number>;
  units: string;
  description: string;
}

export interface TemplateInfo {
  name: string;
  summary: string;
  makes: string[];
  anchors: string[];
  print_notes: string[];
  params: TemplateParameter[];
}

/** What a reference photo gave up, and the caveat that travels with it. */
export interface UploadedImage {
  path: string;
  name: string;
  bytes: number;
  type: string;
  measured: Record<string, string | number | boolean | null>;
  note: string;
  /** Every figure is in PIXELS until somebody supplies one real dimension. */
  needs_scale: boolean;
}

export interface Health {
  model: { ok?: boolean; message?: string };
  capability: { tier: string; headline: string };
  render_version?: number | string;
  mesh_version?: number | string;
  printer: Record<string, unknown>;
  bed: Record<string, unknown>;
  /**
   * The nozzle and layer height every verdict is measured against.
   *
   * Optional because an older engine does not send it - the field was added
   * for the landing screen, which says what a request will be measured against
   * BEFORE it is made. A client that assumed it was there would draw "undefined
   * mm nozzle" against a server one version behind.
   */
  print?: Record<string, unknown>;
  materials: string[];
  /**
   * Which material the server builds in when the request names none.
   *
   * NOT `materials[0]`. That list is sorted, so its head is whatever happens
   * to sort first - and the day the shop's full stock went into the config it
   * became "asa" while the server still built in PETG. The app was then
   * offering to print everything in a material nobody had chosen.
   *
   * Optional because an engine one version behind does not send it, and then
   * the app names no material rather than guessing at one.
   */
  material_default?: string;
  templates: string[];
}

/**
 * A failure with a sentence somebody can act on.
 *
 * The server answers a refused edit with 422 and a message that already
 * explains which wall was too thick and why - see Handler._edited. Replacing
 * that with "request failed" throws away the only useful part, so the body is
 * read on every error path and the status is kept beside it.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly url: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** The model said no, as opposed to the machine being unreachable. */
  get isRefusal(): boolean {
    return this.status === 422 || this.status === 415 || this.status === 400;
  }

  /** Nothing answered at all: no route, no server, or it timed out. */
  get isUnreachable(): boolean {
    return this.status === 0;
  }
}

export class Api {
  constructor(readonly base: string = LOOPBACK) {}

  // -- plumbing -----------------------------------------------------------

  /**
   * fetch with a deadline and the server's own error text.
   *
   * WITHOUT THE TIMEOUT THERE IS NO ERROR AT ALL. A phone with no route to
   * the host does not refuse the connection, it waits - so the app sits on a
   * spinner and the user is told nothing. AbortController turns that into a
   * sentence.
   */
  private async call(path: string, init: RequestInit, timeout: number): Promise<Response> {
    const url = `${this.base}${path}`;
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), timeout);

    let response: Response;
    try {
      response = await fetch(url, { ...init, signal: abort.signal });
    } catch (error: any) {
      if (error?.name === 'AbortError') {
        throw new ApiError(
          `the machine did not answer within ${Math.round(timeout / 1000)}s`,
          0,
          url,
        );
      }
      throw new ApiError(`nothing is answering at ${this.base}`, 0, url);
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const body = await response.text();
        // The server sends {"error": "..."} for everything it refuses.
        const parsed = JSON.parse(body);
        detail = parsed?.error ?? parsed?.message ?? body ?? detail;
      } catch {
        /* a non-JSON body: the status line is all there is */
      }
      throw new ApiError(detail, response.status, url);
    }
    return response;
  }

  private async json<T>(path: string, init: RequestInit, timeout: number): Promise<T> {
    const response = await this.call(path, init, timeout);
    return (await response.json()) as T;
  }

  private post<T>(path: string, body: unknown, timeout: number = TIMEOUTS.edit): Promise<T> {
    return this.json<T>(
      path,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      timeout,
    );
  }

  // -- the machine --------------------------------------------------------

  health(): Promise<Health> {
    return this.json<Health>('/api/health', { method: 'GET' }, TIMEOUTS.quick);
  }

  catalogue(): Promise<Catalogue> {
    return this.json<Catalogue>('/api/operations', { method: 'GET' }, TIMEOUTS.quick);
  }

  /** What this machine has spent - measured, not counted. */
  usage() {
    return this.json<Usage>('/api/usage', { method: 'GET' }, TIMEOUTS.quick);
  }

  /** What the machine is working on, and what it just finished. */
  jobs() {
    return this.json<{ jobs: MachineJob[] }>('/api/jobs', { method: 'GET' }, TIMEOUTS.quick);
  }

  /**
   * One template as data: every parameter with its bounds, units and
   * description, straight off the Pydantic schema.
   *
   * Read, never used to build a form that replaces the sentence. Rule 32 puts
   * English first and parameters second; this is what lets the Machine screen
   * say what a template actually accepts instead of listing its name.
   */
  templateInfo(name: string) {
    return this.json<TemplateInfo>(
      `/api/template/${encodeURIComponent(name)}`,
      { method: 'GET' },
      TIMEOUTS.quick,
    );
  }

  // -- making something ---------------------------------------------------

  /**
   * Ask for a part in words. Returns a job id, not a part.
   *
   * A build runs minutes rather than seconds - the model is asked, a spec is
   * filled, geometry is built and every check is run - so the server answers
   * immediately with an id and the client watches. Nothing here waits.
   */
  generate(request: string, material: string, imagePath?: string) {
    return this.post<{ job: string }>(
      '/api/generate',
      { request, material, image_path: imagePath ?? null },
      TIMEOUTS.quick,
    );
  }

  /**
   * Where a job has got to.
   *
   * POLLED, NOT STREAMED. The server offers server-sent events and they are
   * the right thing in a browser; React Native's fetch has no streaming body,
   * so an EventSource here would mean a third-party polyfill holding a socket
   * open across a screen lock. This route returns the WHOLE event list every
   * time - the Job class keeps it for exactly this reason - so a poll that
   * misses a beat loses nothing.
   */
  job(id: string) {
    return this.json<JobState>(`/api/job/${id}`, { method: 'GET' }, TIMEOUTS.quick);
  }

  parts() {
    return this.json<{ parts: LibraryPart[] }>('/api/parts', { method: 'GET' }, TIMEOUTS.quick);
  }

  /**
   * One page of the library, searched and filtered by the ENGINE.
   *
   * WHY NOT `parts()` AND FILTER HERE. That is what the gallery did, and it
   * is fine at forty models: the whole library crosses the wire, the client
   * holds it in memory and filters it on every keystroke. At four hundred it
   * is a slow open and a phone drawing cards nobody asked to see, and the
   * point of a gallery that size is finding ONE of them.
   *
   * The engine already owns a search that matches a part's name, its
   * template, its material, the prompt that made it and the file it arrived
   * as. This asks that search the question instead of copying it.
   *
   * `parts()` is unchanged and still returns everything - the other screens
   * want the whole list and are right to.
   */
  libraryPage(options: LibraryQuery = {}) {
    const query = new URLSearchParams();
    if (options.q) query.set('q', options.q);
    if (options.show && options.show !== 'all') query.set('show', options.show);
    if (options.sort && options.sort !== 'newest') query.set('sort', options.sort);
    if (options.material) query.set('material', options.material);
    if (options.tag) query.set('tag', options.tag);
    if (options.limit) query.set('limit', String(options.limit));
    if (options.cursor) query.set('cursor', options.cursor);
    if (options.builds === 'all') query.set('builds', 'all');
    const tail = query.toString();
    return this.json<LibraryAnswer>(
      `/api/parts${tail ? `?${tail}` : ''}`,
      { method: 'GET' },
      TIMEOUTS.quick,
    );
  }

  /**
   * What is known about printing one part - measured, plus a slicer's own
   * figures when `slice` is asked for and a slicer is installed.
   *
   * SLICING IS OPT-IN because it takes seconds. A gallery that sliced every
   * part it listed would be a gallery nobody could scroll; this is asked for
   * on the screen where somebody is deciding what to print.
   */
  printFacts(name: string, options: { printer?: string; slice?: boolean } = {}) {
    const query = new URLSearchParams();
    if (options.printer) query.set('printer', options.printer);
    if (options.slice) query.set('slice', '1');
    const tail = query.toString();
    return this.json<PrintFacts>(
      `/api/part/${encodeURIComponent(name)}/print${tail ? `?${tail}` : ''}`,
      { method: 'GET' },
      options.slice ? TIMEOUTS.upload : TIMEOUTS.quick,
    );
  }

  /** Every machine this engine can check a part against. */
  printers() {
    return this.json<PrintersAnswer>('/api/printers', { method: 'GET' }, TIMEOUTS.quick);
  }

  part(name: string) {
    return this.json<PartDetail>(
      `/api/part/${encodeURIComponent(name)}`,
      { method: 'GET' },
      TIMEOUTS.quick,
    );
  }

  /**
   * Check a part again, now, against the profile as it stands today.
   *
   * SYNCHRONOUS, BECAUSE IT IS CHEAP - measured at 0.3s on a part whose build
   * took 151s. The expensive thing in a build is the model call, not the
   * checking. It writes nothing: a re-check is a reading, and overwriting
   * run.json would destroy the record of what the part was given when it was
   * made.
   */
  verify(name: string) {
    return this.post<{ name: string; checks: Checks }>(
      `/api/part/${encodeURIComponent(name)}/verify`,
      {},
      TIMEOUTS.preview,
    );
  }

  /** A built part's geometry, for the same viewport the imports use. */
  async partGlb(name: string): Promise<ArrayBuffer> {
    const response = await this.call(
      `/api/part/${encodeURIComponent(name)}/glb`,
      { method: 'GET' },
      TIMEOUTS.preview,
    );
    return response.arrayBuffer();
  }

  /**
   * One turntable frame of a part, as a URL for `<Image>` rather than bytes.
   *
   * The server renders and caches these, so a library of sixteen parts costs
   * sixteen cached PNGs rather than sixteen GLB downloads and sixteen GL
   * contexts. `w` is clamped server-side to 160..1200 and the frame is always
   * 0.78 as tall as it is wide, which is what the tiles size themselves on.
   */
  frameUrl(
    name: string,
    step: number,
    width: number,
    /**
     * Which of the part's two orientations to draw.
     *
     * RULE 21: print orientation and assembled orientation are SEPARATE
     * FUNCTIONS, never one derived from the other by rotation. The STL on disk
     * is the print layout - a birdhouse is a box with its roof panels lying
     * flat beside it, because that is how it prints without support - and the
     * assembled form is a rebuild the template provides.
     *
     * `assembled` is what the GLB always is, so it is the default here too.
     * `print` is the only way to see how the thing actually comes off the bed,
     * and until now no client on the phone asked for it: a person was shown a
     * birdhouse and had no way to learn it arrives in three pieces.
     */
    layout: 'assembled' | 'print' = 'assembled',
  ): string {
    return (
      `${this.base}/api/part/${encodeURIComponent(name)}/frame/${step}` +
      `?w=${Math.round(width)}&layout=${layout}`
    );
  }

  /**
   * One of a part's rendered images, by name, for a screen to draw.
   *
   * RULE 27: "The height map is the primary geometry-verification visual, not
   * the shaded render" - because a flat-shaded renderer cannot show a recess
   * whose floor shares a normal with the surrounding face. Rule 28: no part is
   * done until one has been generated AND LOOKED AT, which needs somewhere to
   * look at it.
   *
   * Every part on disk has had one since it was built. The only way to reach a
   * PNG was `partFileUrl(name, 'png')`, which globs out/*.png, takes whichever
   * sorts first, and serves it as an attachment - so it happened to be the
   * height map, by alphabet, offered as a download.
   *
   * `kind` is one of heightmap, section, preview. Cached hard: a built part's
   * renders never change, because a refinement writes a new part.
   */
  renderUrl(name: string, kind: 'heightmap' | 'section' | 'preview'): string {
    return `${this.base}/api/part/${encodeURIComponent(name)}/render/${kind}`;
  }

  /**
   * A file the part has on disk, by extension.
   *
   * Only what `PartDetail.files` lists: the server serves stl, step, 3mf and
   * png and 404s anything else, so offering a format that is not in that list
   * is offering a download that fails.
   */
  partFileUrl(name: string, ext: string): string {
    return `${this.base}/api/part/${encodeURIComponent(name)}/file/${ext}`;
  }

  /**
   * Send a reference photo up and get back where it landed and what it says.
   *
   * The bytes go raw in the body, as with a model: the server checks the magic
   * bytes rather than trusting the name, and generates the name it saves under
   * itself. A photo is a few megabytes, so unlike a model this one can go
   * through fetch without worrying about the heap.
   */
  uploadImage(bytes: ArrayBuffer, mime: string): Promise<UploadedImage> {
    return this.json<UploadedImage>(
      '/api/upload',
      { method: 'POST', headers: { 'Content-Type': mime }, body: bytes as any },
      TIMEOUTS.upload,
    );
  }


  /**
   * Change a built part by describing the change. CLAUDE.md rule 32.
   *
   * "Make this roof a triangular roof." The engine reads that against the
   * part's own template schema first, deterministically, and only asks the
   * model for what a parser cannot decide - so a shape word takes seconds and
   * never depends on a 7B model having a good day.
   *
   * Returns a job, like a generate: the part is rebuilt from its spec rather
   * than nudged, so the result is exact rather than a re-roll.
   */
  refine(name: string, instruction: string) {
    return this.post<{ job: string }>(
      '/api/refine',
      { name, instruction },
      TIMEOUTS.quick,
    );
  }

  /**
   * Remove a part and everything in it. There is no undo.
   *
   * The server refuses anything resolving outside the directories it manages -
   * see `_owned_directory`. A confirmation in the client is a courtesy; that
   * guard is what makes the route safe, because a client is not a security
   * boundary.
   */
  deletePart(name: string) {
    return this.post<{ ok: boolean; removed: string; files: number }>(
      `/api/part/${encodeURIComponent(name)}/delete`,
      {},
      TIMEOUTS.quick,
    );
  }

  /**
   * Give a part a different directory name.
   *
   * The directory is what every route resolves and what the clients navigate
   * by, so this is the name that matters. The spec's own name is deliberately
   * left alone - it is recorded in run.json and regression.json, and rewriting
   * it would leave those disagreeing with the file they describe.
   */
  renamePart(name: string, wanted: string) {
    return this.post<{ ok: boolean; dir: string; was?: string }>(
      `/api/part/${encodeURIComponent(name)}/rename`,
      { name: wanted },
      TIMEOUTS.quick,
    );
  }

  /**
   * Set some of a part's own numbers to exactly what was asked for.
   *
   * A SLIDER IS NOT A SENTENCE, which is why this is not `refine`. The parser
   * binds a number to a field by the words near it, and the obvious phrasing
   * collides - "drain dia 6mm" claims `drain_dia_mm` and `entrance_dia_mm`
   * equally, because both own the word "dia" at the same distance. The parser
   * does the right thing with that and asks instead of guessing, which as a
   * slider is a control that moves and changes nothing. A control that already
   * knows which field it is does not go through a parser to say so.
   *
   * Rule 32 is untouched: English is still the way in, and this is the
   * implementation the rule says the parameters are.
   *
   * Returns a job, like a generate. No model is involved - the spec is edited
   * and the part rebuilt - so it is seconds rather than minutes, but it goes
   * through the same screen for the same reason: it is a real build with real
   * checks at the end of it.
   */
  setParams(name: string, values: Record<string, number | string | boolean>) {
    return this.post<{ job: string }>(
      `/api/part/${encodeURIComponent(name)}/params`,
      { values },
      TIMEOUTS.quick,
    );
  }

  /**
   * Open a part this machine built as an editing session with sliders.
   *
   * The mesh is read off disk on the server - it never left the machine - so
   * this costs nothing on the wire whatever the part weighs.
   */
  projectFromPart(name: string) {
    return this.post<Project>('/api/project/from-part', { name }, TIMEOUTS.upload);
  }

  // -- a project ----------------------------------------------------------

  /**
   * Send a model up and get an editing session back.
   *
   * The bytes go in the body with the name in a header, which is what
   * /api/project takes - no multipart, because the server parses none and a
   * boundary-encoded 40 MB STL would cost a copy at both ends for nothing.
   */
  async open(bytes: ArrayBuffer, filename: string, units?: string): Promise<Project> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/octet-stream',
      'X-Filename': filename,
    };
    if (units) headers['X-Units'] = units;

    return this.json<Project>(
      '/api/project',
      { method: 'POST', headers, body: bytes as any },
      TIMEOUTS.upload,
    );
  }

  project(id: string): Promise<Project> {
    return this.json<Project>(`/api/project/${id}`, { method: 'GET' }, TIMEOUTS.quick);
  }

  /**
   * The geometry to draw, and whether it is the proxy rather than the mesh.
   *
   * The header matters to the user: a preview built from a simplified copy is
   * not what they will print, and the viewport says so rather than letting
   * them wonder why the render and the export disagree.
   */
  async preview(id: string): Promise<{ glb: ArrayBuffer; simplified: boolean }> {
    const response = await this.call(
      `/api/project/${id}/preview`,
      { method: 'GET' },
      TIMEOUTS.preview,
    );
    return {
      glb: await response.arrayBuffer(),
      simplified: response.headers.get('X-Preview-Simplified') === '1',
    };
  }

  addEdit(id: string, kind: string, values: Record<string, unknown> = {}) {
    return this.post<{ added: string; project: Project }>(`/api/project/${id}/edit`, {
      kind,
      values,
    });
  }

  /**
   * Move one slider.
   *
   * `final` is pointer-up and it is not a detail: with it false the geometry
   * updates and the printability verdict waits, which is the difference
   * between 43 ms and 488 ms a move. Sending true on every frame of a drag
   * makes the viewport unusable; never sending it at all leaves a green tick
   * describing the previous value, which is worse than no tick.
   */
  setValue(id: string, opId: string, name: string, value: unknown, final: boolean) {
    return this.post<{ clamped: unknown; project: Project }>(
      `/api/project/${id}/edit/${opId}`,
      { name, value, final },
    );
  }

  toggle(id: string, opId: string, enabled: boolean) {
    return this.post<{ project: Project }>(`/api/project/${id}/edit/${opId}`, { enabled });
  }

  remove(id: string, opId: string) {
    return this.post<{ project: Project }>(`/api/project/${id}/edit/${opId}`, {
      remove: true,
    });
  }

  say(id: string, sentence: string) {
    return this.post<Said>(`/api/project/${id}/say`, { sentence });
  }

  /** Where the full mesh lives. The export is never the proxy. */
  exportUrl(id: string, format: 'stl' | 'glb'): string {
    return `${this.base}/api/project/${id}/export.${format}`;
  }
}
