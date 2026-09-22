/**
 * The handful of things the app remembers between launches.
 *
 * ONE FILE, AND ONLY WHAT ACTUALLY CHANGES BEHAVIOUR. Rule 29 - a value with
 * no real source is not written down and not guessed at - applies to the
 * client as much as to the engine, so this holds exactly two things: where the
 * machine is, and which material to ask for by default. A "preferences" screen
 * padded out with switches that do nothing is worse than no screen, because
 * every one of them is a promise the app does not keep.
 *
 * WHY A FILE RATHER THAN AsyncStorage. AsyncStorage is not installed and this
 * needs one object. expo-file-system is already here for the uploads, its
 * document directory survives an app update, and the result is a JSON file a
 * person can read - which matters the first time somebody has to work out why
 * the app is talking to the wrong address.
 *
 * A READ THAT FAILS IS NOT AN ERROR. First launch has no file; a half-written
 * file is possible if the process died mid-save. Both mean "use the defaults",
 * because a settings file is not worth crashing an app over, and both are the
 * same recovery.
 *
 * THE ADDRESS PARSING LIVES IN src/address.ts, not here - see the note at the
 * top of that file. This module touches the filesystem and that one does not,
 * which is what makes the rules in it testable.
 */

import { Directory, File, Paths } from 'expo-file-system';

import { cleanBase, LOOPBACK } from './address';

export interface Settings {
  /**
   * The address of the machine running `whittle web`.
   *
   * Typed by a person, so it is normalised on the way in rather than trusted:
   * see `cleanBase`.
   */
  base: string;
  /**
   * The material to ask for when nothing else is said, or null for "whatever
   * the machine lists first".
   *
   * Null rather than a hardcoded 'petg': the material list comes from the
   * machine's own config, and a client that defaults to a material the
   * machine does not have sends a generate that fails for a reason nobody
   * could see on screen.
   */
  material: string | null;
}

export const DEFAULTS: Settings = {
  base: LOOPBACK,
  material: null,
};

const FILE_NAME = 'settings.json';

function handle(): File {
  return new File(new Directory(Paths.document), FILE_NAME);
}

export async function load(): Promise<Settings> {
  try {
    const file = handle();
    if (!file.exists) return { ...DEFAULTS };
    const parsed = JSON.parse(await file.text()) as Partial<Settings>;
    // FIELD BY FIELD, NOT A SPREAD. The file is whatever was on disk, which
    // includes a settings file written by an older build with a field this
    // one no longer has. Taking only what is understood, and only when it is
    // the right type, means an old file downgrades to the defaults rather
    // than putting a number where the app expects a string.
    const base = typeof parsed.base === 'string' ? cleanBase(parsed.base) : null;
    return {
      base: base ?? DEFAULTS.base,
      material: typeof parsed.material === 'string' ? parsed.material : null,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

/**
 * Write the settings out.
 *
 * Returns nothing and throws nothing: a save that failed must not take a
 * screen down with it, and the value is already live in memory either way.
 * What is lost is that it survives a restart, which the next save fixes.
 */
export async function save(settings: Settings): Promise<void> {
  try {
    const file = handle();
    if (!file.exists) file.create({ intermediates: true });
    file.write(JSON.stringify(settings, null, 2));
  } catch {
    /* see above: not worth a crash */
  }
}
