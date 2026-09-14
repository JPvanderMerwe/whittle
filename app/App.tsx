/**
 * whittle, on the phone.
 *
 * Four places to be, and which one is decided by a single tagged value rather
 * than by a navigation library. There is nothing yet for a router to do that
 * this does not: no deep links, no tab bar, no stack anybody goes back up
 * more than one step of. Adding one before there is a use for it is building
 * the thing that will be wrong later.
 *
 *   start    the two ways in - describe a part, or open a file - and the library
 *   making   a generate running on the machine, with its own log
 *   part     something built: geometry, verdict, options
 *   editing  an imported mesh and its stack of sliders
 *
 * THE WORK LIVES ON THE SERVER. What is held here is the last payload it sent,
 * which is why every mutation hands back a whole Project and the screen
 * replaces it wholesale: the edit stack, the cache and the printability
 * verdict are all the engine's. A client that kept its own copy would be a
 * second answer to "what does this model look like now".
 */

import { StatusBar } from 'expo-status-bar';
import React, { useState } from 'react';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { api, type BuiltPart, type Project } from './src/api';
import { EditScreen } from './src/screens/Edit';
import { MakingScreen } from './src/screens/Making';
import { PartScreen } from './src/screens/Part';
import { StartScreen } from './src/screens/Start';
import { Ground } from './src/ui';

type Where =
  | { at: 'start' }
  | { at: 'making'; jobId: string; request: string }
  | { at: 'part'; name: string; built?: BuiltPart }
  | { at: 'editing'; project: Project };

export default function App() {
  const [where, setWhere] = useState<Where>({ at: 'start' });
  const start = () => setWhere({ at: 'start' });

  return (
    <SafeAreaProvider>
      {/* The ground is always the machine's shell, so the status bar's text is
          light on every screen rather than guessed at per screen. Android
          draws edge to edge and the bar has no background of its own to set -
          what is behind it is the Ground below. */}
      <StatusBar style="light" />
      <Ground>
        <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom']}>
          {where.at === 'start' ? (
            <StartScreen
              api={api}
              onOpened={(project) => setWhere({ at: 'editing', project })}
              onBuilding={(jobId, request) => setWhere({ at: 'making', jobId, request })}
              onPart={(name) => setWhere({ at: 'part', name })}
            />
          ) : null}

          {where.at === 'making' ? (
            <MakingScreen
              api={api}
              jobId={where.jobId}
              request={where.request}
              onBuilt={(built) => setWhere({ at: 'part', name: built.dir ?? built.name, built })}
              onGiveUp={start}
            />
          ) : null}

          {where.at === 'part' ? (
            <PartScreen
              api={api}
              name={where.name}
              built={where.built}
              onClose={start}
              // A CHANGE IS A BUILD. Asking for a triangular roof rebuilds the
              // part from its spec, so it goes through the same screen a first
              // generate does - same log, same rig, same result.
              onChanging={(jobId, request) => setWhere({ at: 'making', jobId, request })}
              onEdit={(project) => setWhere({ at: 'editing', project })}
            />
          ) : null}

          {where.at === 'editing' ? (
            <EditScreen
              api={api}
              project={where.project}
              onProject={(project) => setWhere({ at: 'editing', project })}
              onClose={start}
            />
          ) : null}
        </SafeAreaView>
      </Ground>
    </SafeAreaProvider>
  );
}
