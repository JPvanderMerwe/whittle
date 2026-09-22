/**
 * The file somebody shared into whittle.
 *
 * ANDROID DELIVERS A SHARED FILE AS AN INTENT EXTRA, and nothing in React
 * Native or in any Expo package installed here reads intent extras -
 * `Linking` handles ACTION_VIEW urls and stops there. So this is a small
 * native module rather than a wrapper around something that already existed;
 * see android/.../WhittleShareModule.kt for what it does and why it copies
 * rather than handing back a `content://` Uri.
 *
 * A LOCAL MODULE UNDER ./modules, because `expo prebuild` deletes and
 * regenerates android/ - native code written in there is gone the next time
 * the manifest changes. Autolinking scans ./modules by default.
 */

import { requireOptionalNativeModule } from 'expo-modules-core';

export interface SharedFile {
  /** A file:// path in this app's cache. Readable by fetch and expo-file-system. */
  uri: string;
  /** What the file is called where it came from - "LCD-knob.stl", not an id. */
  name: string;
  bytes: number;
}

interface WhittleShareModule {
  takeSharedFile(): Promise<SharedFile | null>;
  hasSharedFile(): boolean;
}

/**
 * The native side, looked up WHEN IT IS NEEDED rather than at import time.
 *
 * `const native = requireOptionalNativeModule(...)` at module scope runs while
 * the JS bundle is still being evaluated, which can be before the native
 * module registry has been populated - and because the optional form returns
 * null rather than throwing, that null is then cached for the life of the
 * process. The share silently never arrives and nothing anywhere says why.
 *
 * Resolving per call costs a registry lookup and cannot go stale.
 *
 * OPTIONAL, ON PURPOSE. The throwing form would take the app down on launch in
 * a build made before this module existed, and on any platform but Android.
 * One behaviour depends on it; it should degrade to "nobody shared anything".
 */
function share(): WhittleShareModule | null {
  try {
    return requireOptionalNativeModule<WhittleShareModule>('WhittleShare') ?? null;
  } catch {
    return null;
  }
}

/** True when this launch carried a file. Does not consume it. */
export function hasSharedFile(): boolean {
  try {
    return share()?.hasSharedFile() ?? false;
  } catch {
    return false;
  }
}

/**
 * The shared file, once.
 *
 * CONSUMED ON READ - the native side clears the intent, because a launch
 * intent outlives the launch. Without that, an app opened once from a share
 * would re-import the same file on every resume.
 */
export async function takeSharedFile(): Promise<SharedFile | null> {
  try {
    return (await share()?.takeSharedFile()) ?? null;
  } catch (error) {
    // A share that cannot be read is one import that does not happen, not a
    // reason to take the app down on launch - but it is not nothing either.
    // Swallowing it silently is how the first version of this failed for an
    // hour while `hasSharedFile()` kept reporting true.
    console.warn('[whittle-share] could not take the shared file:', String(error));
    return null;
  }
}
