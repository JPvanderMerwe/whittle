/**
 * Let whittle receive a model file from anywhere else on the phone.
 *
 * THE ASK: "I want to share already printed or used stl's that are working
 * and that I might want to edit with whittle."
 *
 * Without this the only way in is the app's own picker - so bringing in an STL
 * means opening whittle, remembering where the importer is, and hunting for a
 * file you were already looking at. With it, whittle is in the share sheet of
 * a browser download, a file manager or a chat app, and it is one tap from
 * wherever the file already is.
 *
 * THIS WAS WRITTEN ONCE AND DELETED BEFORE SHIPPING. Declaring the filter is
 * the easy half; the file arrives in an intent extra that nothing in React
 * Native or in any installed Expo package can read. A filter with no receiver
 * puts whittle in the share sheet as an app that accepts your STL and silently
 * loses it, which is a worse promise than not appearing. It is back now
 * because modules/whittle-share reads the extra - see that module for how.
 *
 * WHY THE MIME LIST IS THIS BROAD. Android matches on MIME type and nothing
 * agrees about an STL's. The registered type is `model/stl`, a browser
 * download routinely arrives as `application/octet-stream`, and file managers
 * send `*` + `/*` for anything they do not recognise. The app's own picker
 * already takes everything for the same reason, and the server checks magic
 * bytes rather than trusting a name - so a wrong file is a clear refusal
 * rather than a mess. Declaring only `model/stl` would make whittle absent
 * from the share sheet at exactly the moment somebody has downloaded
 * something, which is the moment this exists for.
 */

const { withAndroidManifest, AndroidConfig } = require('expo/config-plugins');

/** What a shared model may arrive labelled as. See the note above. */
const MIME_TYPES = ['model/*', 'application/octet-stream', '*/*'];

/** SEND for one file; SEND_MULTIPLE because file managers use it for one too. */
const SHARE_ACTIONS = [
  'android.intent.action.SEND',
  'android.intent.action.SEND_MULTIPLE',
];

const withShareTarget = (config) =>
  withAndroidManifest(config, (mod) => {
    const application = AndroidConfig.Manifest.getMainApplicationOrThrow(mod.modResults);
    const activity = application.activity?.find(
      (a) => a.$['android:name'] === '.MainActivity',
    );
    if (!activity) {
      // A MISSING MAIN ACTIVITY IS A BROKEN PREBUILD, not something to paper
      // over: skipping silently would ship an app simply absent from the share
      // sheet with nothing to say why.
      throw new Error(
        'withShareTarget: no .MainActivity in the manifest to attach a share ' +
          'filter to. Has prebuild run?',
      );
    }

    activity['intent-filter'] = activity['intent-filter'] || [];

    // IDEMPOTENT, AND WITHOUT A MARKER OF OUR OWN. Prebuild runs against a
    // manifest that may already carry these, and a duplicated intent-filter is
    // a duplicated entry in the share sheet. An earlier version tagged each
    // filter with a custom attribute to find them again - a non-namespaced
    // attribute in a shipped manifest, which the merger may reject and which
    // would be read by nothing. The action name already identifies them.
    const isOurs = (filter) =>
      (filter.action || []).some((a) => SHARE_ACTIONS.includes(a.$?.['android:name']));
    activity['intent-filter'] = activity['intent-filter'].filter((f) => !isOurs(f));

    for (const action of SHARE_ACTIONS) {
      activity['intent-filter'].push({
        action: [{ $: { 'android:name': action } }],
        category: [{ $: { 'android:name': 'android.intent.category.DEFAULT' } }],
        data: MIME_TYPES.map((mimeType) => ({ $: { 'android:mimeType': mimeType } })),
      });
    }

    return mod;
  });

module.exports = withShareTarget;
