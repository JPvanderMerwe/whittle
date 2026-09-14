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
 * Loopback, because of `adb reverse tcp:8765 tcp:8765`. The phone's own
 * localhost is forwarded to the machine running `whittle web`, which is the
 * same arrangement mobile/lib/api.dart documents - it needs no LAN address
 * typed into the app, survives the laptop changing networks, and does not put
 * the engine on the network for anyone else to reach.
 *
 * A device that is not plugged in has no route, and the connection screen
 * says so in those terms rather than showing a spinner for ever.
 */

const DEFAULT_BASE = 'http://127.0.0.1:8765';

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
  name: string;
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
  assumptions: string[];
  report_md: string;
  files: string[];
  options?: PartOption[];
  elapsed_s?: number;
  attempts?: number;
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
  printer: Record<string, unknown>;
  bed: Record<string, unknown>;
  materials: string[];
  templates: unknown[];
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
}

export class Api {
  constructor(readonly base: string = DEFAULT_BASE) {}

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
      throw new ApiError(
        `cannot reach whittle at ${this.base} - is \`whittle web\` running, and ` +
          'has `adb reverse tcp:8765 tcp:8765` been set up?',
        0,
        url,
      );
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

  part(name: string) {
    return this.json<Record<string, unknown>>(
      `/api/part/${encodeURIComponent(name)}`,
      { method: 'GET' },
      TIMEOUTS.quick,
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

export const api = new Api();
