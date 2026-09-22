/**
 * What you have used, what it cost, and what it would cost hosted.
 *
 * EVERY FIGURE ON THIS SCREEN IS MEASURED. `/api/usage` sums run.json: each
 * attempt records the model that served it and the tokens that went in and
 * came out, so this is a total over things that happened rather than a counter
 * somebody incremented. A usage screen whose numbers cannot be traced back to
 * a run is a usage screen nobody should believe - and the one place that
 * matters most is the one where somebody is deciding whether to pay.
 *
 * WHAT IS DELIBERATELY NOT HERE, AND WHY
 * --------------------------------------
 * There is no balance, no plan, no "tokens remaining" and no button that takes
 * a card. Not as an oversight and not as a placeholder: there is no hosted
 * service, no account system and no billing backend in this product yet, so
 * every one of those would be a number with nothing behind it or a control
 * that does nothing. Rule 29 is about exactly this - a value with no measured
 * source is not written down, because a wrong figure is worse than no figure,
 * and a fake payment flow is worse than both.
 *
 * WHAT IS TRUE TODAY, and it is the strongest thing this screen can say:
 * building here is free and unmetered, because it runs on the computer in
 * front of you. The tokens counted below were spent by a model on your own
 * machine. Nobody was billed for them and nobody could have been.
 *
 * So the free tier is not a tier - it is the whole product as it stands - and
 * the honest shape of a paid one is stated rather than mocked up: when whittle
 * can build on a machine that is not yours, THAT is what would be metered, and
 * the figures below are what it would have cost. Somebody deciding can see
 * their own real usage first.
 */

import React from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import type { Usage } from '../api';
import { core, pen, space } from '../tokens';
import { Empty, Mono, Panel, Prose, Row, Surface, Verdict } from '../ui';

interface Props {
  usage: Usage | null;
  ready: boolean;
  onFixConnection: () => void;
}

export function YouScreen({ usage, ready, onFixConnection }: Props) {
  if (!ready) {
    return (
      <View style={styles.body}>
        <Empty
          title="your usage is read off the machine"
          hint="Everything on this screen is a sum over the builds on the computer running whittle, so it needs to be reachable."
        />
      </View>
    );
  }

  if (!usage) {
    return (
      <View style={styles.body}>
        <Empty
          title="this engine does not report usage"
          hint="It predates the figures this screen shows. Everything still works; there is simply nothing to total up."
        />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.body}>
      <Prose size="title" weight="bold" color={core.screen}>
        you
      </Prose>

      {/* THE HEADLINE IS THE PRICE, because that is the question this screen
          exists to answer and the answer is a good one. */}
      <Surface step="card" style={styles.headline}>
        <Mono size="display" weight="bold" color={pen.pass}>
          free
        </Mono>
        <Prose size="body" color={core.dim}>
          {usage.why_free}
        </Prose>
      </Surface>

      <Panel title="what you have made">
        <Row label="builds that worked" value={String(usage.built)} />
        {/* A DRAFT IS NOT A FAILURE TO HIDE. It is a run that happened, it
            cost the same tokens, and it is on disk with the reason it stopped.
            Leaving it out of a usage total would make the total wrong. */}
        <Row label="that did not" value={String(usage.drafts)} />
        <Row label="runs in total" value={String(usage.runs)} />
        {usage.first_run_at ? (
          <Row label="since" value={onDay(usage.first_run_at)} />
        ) : null}
      </Panel>

      <Panel title="what it cost">
        <Row label="model tokens" value={usage.tokens.toLocaleString()} />
        <Row label="  of that, prompt" value={usage.prompt_tokens.toLocaleString()} />
        <Row label="  generated" value={usage.generated_tokens.toLocaleString()} />
        <Row label="model calls" value={String(usage.model_calls)} />
        <Row label="machine time" value={asTime(usage.machine_seconds)} />
        <Prose size="body" color={core.dim}>
          These are the tokens a model on your own computer read and wrote. They are counted
          because they are the thing a hosted service would charge for - not because anything
          here is charging.
        </Prose>
      </Panel>

      {usage.models.length ? (
        <Panel title="which models did the work">
          {usage.models.map((model) => (
            <Row key={model.name} label={model.name} value={`${model.attempts} attempts`} />
          ))}
        </Panel>
      ) : null}

      <Panel title="a hosted whittle, if there is one">
        {/* SAID, NOT MOCKED UP. A "buy tokens" button with no service behind
            it is a control that lies, and a balance with no account behind it
            is a number with no source. What can honestly go here is the shape
            of the thing and the figures above, so that somebody deciding is
            looking at their own real usage rather than a sample. */}
        <Verdict
          state="info"
          text="not built yet - there is no account, no balance and nothing to buy"
        />
        <Prose size="body" color={core.dim}>
          whittle runs on your machine and that is the point of it: no signal, no account, no
          per-part cost. A hosted option would be for the times that is not enough - a phone with
          no computer near it, or a model too big for the machine you have.
        </Prose>
        <Prose size="body" color={core.dim}>
          If it arrives, the figures above are what it would meter, and they are already yours to
          look at. Nothing on this screen will start costing money without saying so first.
        </Prose>
      </Panel>

      <Panel title="the connection">
        <Prose size="body" color={core.dim}>
          Where the engine is, which printer it builds against and what it is doing right now are
          on the machine tab.
        </Prose>
        <Verdict state="pass" text="nothing you make leaves your own computer" />
      </Panel>
    </ScrollView>
  );
}

/** A unix stamp as a day, without inventing a clock the server did not send. */
function onDay(stamp: number): string {
  try {
    return new Date(stamp * 1000).toLocaleDateString();
  } catch {
    return '—';
  }
}

/**
 * Seconds as something a person reads.
 *
 * Hours once it is hours: "7782 s" is a figure nobody can hold, and two hours
 * ten is the same fact.
 */
function asTime(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

const styles = StyleSheet.create({
  body: {
    padding: space.base,
    gap: space.base,
    paddingBottom: space.room,
  },
  headline: {
    padding: space.base,
    gap: space.snug,
  },
});
