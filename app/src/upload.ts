/**
 * Getting a model off the phone and onto the engine.
 *
 * WHY THIS IS NOT IN api.ts. Everything in api.ts is fetch and JSON, which
 * means it runs unchanged in the web app when that is built - v8 section 16
 * blocker 5 is "one API for two clients", and the way to keep that true is to
 * not import a native module into the file both clients share. This one is
 * native on purpose.
 *
 * WHY NOT JUST fetch(bytes)
 * -------------------------
 * The server takes a model up to 150 MB, and a download off Printables is
 * routinely tens of megabytes. `new File(uri).arrayBuffer()` would put all of
 * it in the JavaScript heap, hand a copy to the bridge and let the native side
 * copy it again - three copies of a 90 MB STL on a phone, which is how an app
 * gets killed on a mid-range device with no error anybody can read.
 *
 * expo-file-system's upload streams the file from disk with the body as raw
 * bytes, which is exactly what /api/project reads: Content-Length bytes off
 * the socket with the name in X-Filename. Nothing is multipart, at either end.
 */

import { File, UploadType } from 'expo-file-system';

import { ApiError, type Api, type Project } from './api';

/** What the server says a file may weigh, mirrored so the app can say it first. */
export const MAX_MODEL_BYTES = 150 * 1024 * 1024;

export interface Progress {
  sent: number;
  total: number;
}

/**
 * A file name the server will accept, derived from one the phone gave us.
 *
 * The server checks the name against SAFE_NAME and refuses anything else, and
 * a document picked out of Google Drive routinely arrives called
 * "dragon (1).stl" or with a colon in it. Refusing the upload for that reason
 * would be the machine being difficult about something it can fix itself, so
 * the name is cleaned here and the original is not needed again - the part is
 * identified by what is inside it, not by what the phone called it.
 */
export function safeName(name: string): string {
  const cleaned = (name || 'model.stl')
    .split(/[\\/]/)
    .pop()!
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 120);
  return cleaned.length >= 3 ? cleaned : 'model.stl';
}

/**
 * Send one model up and get the editing session back.
 *
 * The size is checked here as well as on the server, because the useful place
 * to say "that file is 210 MB and the limit is 150" is before spending four
 * minutes of somebody's mobile data discovering it.
 */
export async function uploadModel(
  api: Api,
  uri: string,
  filename: string,
  onProgress?: (progress: Progress) => void,
  units?: string,
): Promise<Project> {
  const file = new File(uri);
  const size = file.size ?? 0;
  if (size > MAX_MODEL_BYTES) {
    throw new ApiError(
      `that file is ${(size / 1048576).toFixed(1)} MB and the limit is ` +
        `${MAX_MODEL_BYTES / 1048576} MB`,
      413,
      uri,
    );
  }

  const name = safeName(filename);
  const headers: Record<string, string> = { 'X-Filename': name };
  if (units) headers['X-Units'] = units;

  const url = `${api.base}/api/project`;

  let result;
  try {
    result = await file.upload(url, {
      httpMethod: 'POST',
      uploadType: UploadType.BINARY_CONTENT,
      mimeType: 'application/octet-stream',
      headers,
      onProgress: onProgress
        ? ({ bytesSent, totalBytes }) => onProgress({ sent: bytesSent, total: totalBytes })
        : undefined,
    });
  } catch (error: any) {
    throw new ApiError(
      `cannot reach whittle at ${api.base} - is \`whittle web\` running, and has ` +
        '`adb reverse tcp:8765 tcp:8765` been set up?',
      0,
      url,
    );
  }

  // A NON-2xx IS A RESOLVED PROMISE HERE, not a rejection - the API rejects
  // only when the file cannot be read or the request never completed. So the
  // status is checked rather than assumed, which is the difference between
  // "that is not an STL" reaching the user and the app trying to parse the
  // refusal as a project.
  if (result.status < 200 || result.status >= 300) {
    let detail = `${result.status}`;
    try {
      detail = JSON.parse(result.body)?.error ?? result.body ?? detail;
    } catch {
      detail = result.body || detail;
    }
    throw new ApiError(detail, result.status, url);
  }

  return JSON.parse(result.body) as Project;
}
