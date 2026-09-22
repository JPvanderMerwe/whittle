/**
 * Getting a file off the machine and onto the phone, where a person can use it.
 *
 * THE APP COULD NOT DOWNLOAD ANYTHING. You could describe a part, watch it
 * build, turn it, read its verdict - and there was no way to get the STL. The
 * server has served `/api/part/<name>/stl` and `/api/part/<name>/file/<ext>`
 * the whole time and no client on the phone ever called either. A modeller you
 * cannot take the model out of is a demo.
 *
 * WHY THE USER PICKS THE FOLDER
 * -----------------------------
 * The obvious spelling is `File.downloadFileAsync(url, Paths.document)`, and
 * it works, and the file is then in the app's own sandbox where nothing else
 * on the phone can open it. That is a download that has not happened as far as
 * the person is concerned: the point of an STL is to hand it to a slicer.
 *
 * So this asks for a real directory - Android's Storage Access Framework, the
 * same picker every other app uses - and writes the file there under its own
 * name. The folder is the person's choice, which also means the app never
 * needs storage permission, never writes somewhere unexpected, and the saved
 * file is visible in the file manager immediately.
 *
 * NO NEW DEPENDENCY. expo-file-system is already here for the uploads and it
 * carries the picker.
 */

import { Directory } from 'expo-file-system';

/**
 * What the server will hand over, and what to call it on the phone.
 *
 * THE SAME ALLOW-LIST THE SERVER KEEPS, and deliberately a copy of it rather
 * than a guess from the extension: `Handler.DOWNLOADABLE` exists so the route
 * can never be talked into serving `spec.yaml` or `model.py`, and a client
 * offering a format that list does not have is offering a download that 404s.
 */
export const SAVEABLE: Record<string, string> = {
  stl: 'model/stl',
  step: 'model/step',
  '3mf': 'model/3mf',
  png: 'image/png',
};

/** What people call these, since "3mf" is not a word most have read. */
export const FORMAT_NOTE: Record<string, string> = {
  stl: 'the mesh - what a slicer wants',
  step: 'solid geometry - what CAD wants',
  '3mf': 'mesh plus units and colour, in one file',
  png: 'the rendered picture',
};

export type SaveResult =
  | { ok: true; where: string }
  | { ok: false; cancelled: true }
  | { ok: false; cancelled: false; message: string };

/**
 * Fetch `url` and write it into a folder the person picks.
 *
 * THE BYTES COME DOWN BEFORE THE PICKER OPENS. Asking for the folder first
 * and then discovering the part has no STL means a person has chosen a
 * destination for a file that was never coming - so the failure that is
 * likeliest, and the only one the server has an opinion about, happens while
 * they are still looking at the screen that offered it.
 */
export async function saveToFolder(
  url: string,
  filename: string,
  mimeType: string,
): Promise<SaveResult> {
  let bytes: ArrayBuffer;
  try {
    const response = await fetch(url);
    if (!response.ok) {
      // The server answers a refusal as {"error": "..."} and that sentence is
      // worth more than the status line - "part 'x' has no STL" tells you
      // this is a draft, which is a fact about the part rather than a fault.
      let detail = `${response.status} ${response.statusText}`;
      try {
        const parsed = JSON.parse(await response.text());
        detail = parsed?.error ?? detail;
      } catch {
        /* a non-JSON body: the status line is all there is */
      }
      return { ok: false, cancelled: false, message: detail };
    }
    bytes = await response.arrayBuffer();
  } catch (error: any) {
    return {
      ok: false,
      cancelled: false,
      message: String(error?.message ?? error),
    };
  }

  let folder: Directory;
  try {
    folder = await Directory.pickDirectoryAsync();
  } catch {
    // A CANCELLED PICKER IS NOT AN ERROR, and it is the commonest way this
    // function ends. Reporting "could not save" to somebody who pressed back
    // is how an app teaches people that its messages are noise.
    return { ok: false, cancelled: true };
  }

  try {
    const file = folder.createFile(filename, mimeType);
    file.write(new Uint8Array(bytes));
    return { ok: true, where: folder.name || 'the folder you chose' };
  } catch (error: any) {
    return {
      ok: false,
      cancelled: false,
      message: String(error?.message ?? error),
    };
  }
}

/**
 * A filename that will survive a filesystem.
 *
 * Part directories are already safe - the server's SAFE_NAME sees to that -
 * but a project's name comes from an uploaded file, which is somebody else's
 * "dragon (1).stl" or worse. This is the same shape as upload.safeName and
 * kept separate because that one is fixing a name on the way UP.
 */
export function saveName(base: string, ext: string): string {
  const cleaned = (base || 'part')
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 60);
  return `${cleaned || 'part'}.${ext}`;
}
