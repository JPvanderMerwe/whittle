/**
 * Where the machine is, as a string a person typed.
 *
 * WHY THIS IS ITS OWN FILE. It started inside src/store.ts, next to the code
 * that reads and writes the settings - and that put two different concerns in
 * one module: parsing what somebody typed, and touching the filesystem. The
 * cost was immediate and concrete. These functions are the only ones in the
 * client with rules worth testing, and the moment a test imported them it
 * pulled expo-file-system in behind them, which node's test runner cannot load
 * at all (`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`).
 *
 * So: no imports, no side effects, and the one piece of the connection that
 * can be proved without a device. src/api.ts reads LOOPBACK from here too,
 * which means importing the API client no longer drags the storage layer in
 * with it either.
 */

/**
 * Where whittle is, out of the box.
 *
 * Loopback, because `adb reverse tcp:8765 tcp:8765` forwards the phone's own
 * localhost to the machine running `whittle web`. No LAN address to type, it
 * survives the laptop changing networks, and it puts the engine on nobody
 * else's network. The Machine screen can change it, and the reason it can is
 * the person on Wi-Fi with no cable.
 */
export const LOOPBACK = 'http://127.0.0.1:8765';

/** The port the engine listens on, filled in when somebody names none. */
const PORT = '8765';

/**
 * Tidy an address a person typed, or return null if it cannot be one.
 *
 * FOUR THINGS GO WRONG WHEN SOMEBODY TYPES A HOST, and all four are silent:
 * a trailing slash makes every path `//api/health`; a missing scheme makes
 * `fetch` refuse; a bare IP with no port reaches port 80 and times out; and
 * trailing whitespace from a paste is invisible on screen. Fixing them here
 * means the Machine screen can say "that is not an address" once, rather than
 * the app failing to connect for a reason that looks like the server being
 * down.
 */
export function cleanBase(typed: string): string | null {
  let text = typed.trim();
  if (!text) return null;
  if (!/^https?:\/\//i.test(text)) text = `http://${text}`;
  text = text.replace(/\/+$/, '');

  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (!url.hostname) return null;
  // A host with no port is port 80, which is not where whittle listens. The
  // engine's own default is what gets filled in, because the alternative is a
  // timeout the person reads as "the machine is off".
  if (!url.port) url.port = PORT;
  return `${url.protocol}//${url.host}`;
}

/**
 * True when this address is the phone's own loopback - the cable, not the
 * network.
 *
 * The Machine screen says something materially different for each: one keeps
 * the geometry off the network entirely and the other does not. A wrong answer
 * here tells somebody their geometry is private when it is not.
 */
export function isLoopback(base: string): boolean {
  try {
    const host = new URL(base).hostname;
    return host === '127.0.0.1' || host === 'localhost' || host === '::1';
  } catch {
    return false;
  }
}
