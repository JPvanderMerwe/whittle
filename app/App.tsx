/**
 * whittle, on the phone.
 *
 * THREE PLACES TO BE, AND A STACK OVER THEM. The tabs are the three things
 * this engine does - make something, look at what you have made, and the
 * machine itself - and they are always reachable. Everything that is about ONE
 * thing covers them: watching a build, a built part, a mesh with sliders on it.
 *
 *   make      a sentence in, a part out          (tab)
 *   library   everything made, as pictures       (tab)
 *   machine   where it is, what it can do        (tab)
 *
 *   making    a build running, with its log      (over the tabs)
 *   part      something built                    (over the tabs)
 *   editing   an imported mesh and its sliders   (over the tabs)
 *
 * WHY THIS SHAPE RATHER THAN THE ONE BEFORE IT. There were four screens and no
 * navigation: one tagged value, and the library was the third segment of a
 * control at the top of the making screen. That made "everything I have made"
 * a mode of making something new, and it left nowhere at all to put a setting
 * - which is why the app had none, and why the server address was a constant
 * nobody could change from a phone.
 *
 * STILL NO ROUTER, and for the same reason as before: no deep links, no URL
 * bar, and a stack nobody goes up more than one step of. What changed is that
 * there are now tabs to remember, so the tagged value has a tab beside it.
 *
 * THE WORK LIVES ON THE SERVER. What is held here is the last payload it sent,
 * which is why every mutation hands back a whole Project and the screen
 * replaces it wholesale: the edit stack, the cache and the printability
 * verdict are all the engine's. A client that kept its own copy would be a
 * second answer to "what does this model look like now".
 *
 * AND SO IS EVERYTHING ABOUT THE MACHINE. Health, the job list and the library
 * are polled once here and passed down - see src/machine.ts for the three
 * clocks and why they differ. Three screens need some of this, and three
 * copies of the polling would disagree the moment one of them was on a tab
 * that was not mounted.
 */

import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AppState, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { Api, type BuiltPart, type Project } from './src/api';
import { useMachine } from './src/machine';
import { EditScreen } from './src/screens/Edit';
import { LibraryScreen } from './src/screens/Library';
import { MachineScreen } from './src/screens/Machine';
import { MakeScreen } from './src/screens/Make';
import { MakingScreen, type JobKind } from './src/screens/Making';
import { PartScreen } from './src/screens/Part';
import { YouScreen } from './src/screens/You';
import { DEFAULTS, load, save, type Settings } from './src/store';
import { Ground, TabBar, type TabName } from './src/ui';
import { takeSharedFile, type SharedFile } from './modules/whittle-share';

/** A screen that covers the tabs, or none. */
type Over =
  | null
  | { at: 'making'; jobId: string; request: string; kind: JobKind }
  | { at: 'part'; name: string; built?: BuiltPart }
  | { at: 'editing'; project: Project };

export default function App() {
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState<TabName>('make');
  const [over, setOver] = useState<Over>(null);
  /**
   * The gallery asked for the file picker.
   *
   * A one-shot, cleared the moment the make screen has acted on it: left set,
   * every later visit to that tab would re-open a picker nobody asked for.
   */
  const [importing, setImporting] = useState(false);
  /**
   * A file shared into whittle from somewhere else on the phone.
   *
   * Picked up at launch and again whenever the app comes back to the front:
   * MainActivity is singleTask, so a share to an app that is already running
   * arrives as a new intent on the existing activity rather than starting a
   * fresh one. Polling on resume is how that reaches JS without a listener -
   * the native side consumes the intent as it reads it, so asking twice is
   * harmless and asking once would miss the second share.
   */
  const [incoming, setIncoming] = useState<SharedFile | null>(null);

  // ONE Api PER ADDRESS. It is immutable by design - the base is readonly, so
  // there is no way for a call in flight to land against a different server
  // than the one it was aimed at - and changing the address makes a new one.
  const api = useMemo(() => new Api(settings.base), [settings.base]);

  // Nothing is polled until the saved address has been read off disk, or the
  // first health check goes to the default and is then immediately repeated
  // against the real one.
  const machine = useMachine(api, loaded);

  useEffect(() => {
    load().then((found) => {
      setSettings(found);
      setLoaded(true);
    });
  }, []);

  useEffect(() => {
    let live = true;
    const look = () => {
      takeSharedFile().then((file) => {
        if (!live || !file) return;
        // STRAIGHT TO THE MAKING SCREEN, which owns the upload progress and
        // the ingest report. A share is an import; it should look like one.
        setTab('make');
        setOver(null);
        setIncoming(file);
      });
    };

    look();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') look();
    });
    return () => {
      live = false;
      subscription.remove();
    };
  }, []);

  const update = useCallback((change: Partial<Settings>) => {
    setSettings((current) => {
      const next = { ...current, ...change };
      // Written in the background: a save that fails must not take the screen
      // with it, and the value is already live either way. See store.save.
      save(next);
      return next;
    });
  }, []);

  const closeOver = useCallback(() => setOver(null), []);
  const connected = Boolean(machine.health);

  return (
    <SafeAreaProvider>
      {/* The ground is always the machine's shell, so the status bar's text is
          light on every screen rather than guessed at per screen. Android
          draws edge to edge and the bar has no background of its own to set -
          what is behind it is the Ground below. */}
      <StatusBar style="light" />
      <Ground>
        <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom']}>
          {/* THE STACK, WHEN THERE IS ONE. It covers the tabs rather than
              living inside one, because a part reached from the library and
              the same part reached straight off a build are the same screen -
              putting it inside a tab would mean two of them. */}
          {over?.at === 'making' ? (
            <MakingScreen
              api={api}
              jobId={over.jobId}
              request={over.request}
              kind={over.kind}
              onBuilt={(built) =>
                setOver({ at: 'part', name: built.dir ?? built.name, built })
              }
              onGiveUp={closeOver}
            />
          ) : null}

          {over?.at === 'part' ? (
            <PartScreen
              api={api}
              parts={machine.parts}
              name={over.name}
              built={over.built}
              onClose={closeOver}
              // A CHANGE IS A BUILD. Asking for a triangular roof rebuilds the
              // part from its spec, so it goes through the same screen a first
              // generate does - same log, same rig, same result.
              onChanging={(jobId, request, kind) =>
                setOver({ at: 'making', jobId, request, kind })
              }
              onEdit={(project) => setOver({ at: 'editing', project })}
              // AN EARLIER BUILD IS A DIFFERENT PART, so opening one replaces
              // the screen rather than stacking - there is nothing to go back
              // up to that the chain panel does not already show.
              onShowPart={(dir) => setOver({ at: 'part', name: dir })}
              // GONE MEANS LEAVE, AND RE-READ. Staying on a screen whose part
              // no longer exists would draw a 404 as an empty viewport, and
              // the library would keep the tile until something else refreshed
              // it.
              onDeleted={() => {
                closeOver();
                setTab('library');
                machine.reloadParts();
              }}
              // THE DIRECTORY IS THE IDENTITY, so the screen follows it and the
              // library re-reads to pick the new name up.
              onRenamed={(dir) => {
                setOver({ at: 'part', name: dir });
                machine.reloadParts();
              }}
            />
          ) : null}

          {over?.at === 'editing' ? (
            <EditScreen
              api={api}
              project={over.project}
              onProject={(project) => setOver({ at: 'editing', project })}
              onClose={closeOver}
            />
          ) : null}

          {/* THE TABS, UNDERNEATH. Kept mounted rather than swapped out so the
              library keeps its search and the half-typed sentence on the make
              screen is still there after looking something up. */}
          <View style={{ flex: 1, display: over ? 'none' : 'flex' }}>
            <View style={{ flex: 1, display: tab === 'make' ? 'flex' : 'none' }}>
              <MakeScreen
                api={api}
                health={machine.health}
                checking={machine.checking}
                jobs={machine.jobs}
                parts={machine.parts}
                material={settings.material}
                onMaterial={(name) => update({ material: name })}
                onOpened={(project) => setOver({ at: 'editing', project })}
                onBuilding={(jobId, request) =>
                  setOver({ at: 'making', jobId, request, kind: 'generate' })
                }
                onPart={(name) => setOver({ at: 'part', name })}
                onWatch={(jobId, request) =>
                  // WATCHING SOMETHING ALREADY RUNNING, and the job list does
                  // carry its kind - but a job worth tapping from the "building
                  // now" strip has been running long enough to appear there, so
                  // the long-job screen is the right one either way.
                  setOver({ at: 'making', jobId, request, kind: 'generate' })
                }
                onFixConnection={() => setTab('machine')}
                onSeeAll={() => setTab('library')}
                openFileNow={importing}
                onOpenedFilePicker={() => setImporting(false)}
                // A BATCH ADDS FORTY ENTRIES WITH NO BUILD FINISHING, and
                // the polling that usually notices a change runs on its own
                // clock. Without this the models are in the library and the
                // gallery shows the list from before them.
                onImported={() => machine.reloadParts()}
                incoming={incoming}
                onTookIncoming={() => setIncoming(null)}
              />
            </View>

            <View style={{ flex: 1, display: tab === 'library' ? 'flex' : 'none' }}>
              <LibraryScreen
                api={api}
                ready={connected}
                parts={machine.parts}
                partsProblem={machine.partsProblem}
                jobs={machine.jobs}
                onReload={machine.reloadParts}
                onPart={(name) => setOver({ at: 'part', name })}
                onWatch={(jobId, request) =>
                  setOver({ at: 'making', jobId, request, kind: 'generate' })
                }
                onFixConnection={() => setTab('machine')}
                // THE IMPORTER LIVES ON THE MAKING SCREEN because that is
                // where the upload progress and the ingest report are already
                // wired. The gallery sends you there with it open rather than
                // growing a second copy of the same flow.
                onImport={() => {
                  setTab('make');
                  setImporting(true);
                }}
              />
            </View>

            <View style={{ flex: 1, display: tab === 'machine' ? 'flex' : 'none' }}>
              <MachineScreen
                api={api}
                // THE NEWEST THING IN THE LIBRARY, which is what this tab
                // offers to print. The library is served newest first, so
                // this is the head - sorting here would be a second opinion
                // about an order the engine has.
                latest={(machine.parts ?? [])[0] ?? null}
                // THE SAME WAY EVERY OTHER SCREEN OPENS A PART. There is one
                // part view and it is an overlay; routing this one through
                // the library tab instead would be a second way in that
                // behaves differently.
                onPart={(name) => setOver({ at: 'part', name })}
                health={machine.health}
                checking={machine.checking}
                problem={machine.problem}
                jobs={machine.jobs}
                onWatch={(jobId, request) =>
                  setOver({ at: 'making', jobId, request, kind: 'generate' })
                }
                onRetry={machine.refresh}
                base={settings.base}
                onBase={(base) => update({ base })}
                material={settings.material}
                onMaterial={(name) => update({ material: name })}
              />
            </View>

            <View style={{ flex: 1, display: tab === 'you' ? 'flex' : 'none' }}>
              <YouScreen
                usage={machine.usage}
                ready={connected}
                onFixConnection={() => setTab('machine')}
              />
            </View>

            {/* THE COUNT OVER THE LIBRARY TAB IS WHAT THE MACHINE IS DOING.
                A build outlives the screen that started it, and this is the
                thing that makes leaving that screen feel like a decision
                rather than a loss. */}
            <TabBar
              value={tab}
              onChange={setTab}
              badge={{ library: machine.jobs.filter((job) => !job.done).length }}
            />
          </View>
        </SafeAreaView>
      </Ground>
    </SafeAreaProvider>
  );
}
