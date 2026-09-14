import React, { useMemo, useState } from 'react';
import { Alert, Pressable, Text, View } from 'react-native';

import {
  Classification, Narrative as NarrativeT, Pack as PackT, PackItem, PackState,
  PackWarningRow, RaceKitDraft, TackleReport, generatePack,
  getAdventureTackle, getKitProvenance, getNarrative, getPack,
  setPackItemState, writeNarrative,
} from '../api';
import { useCached } from '../cache';
import { Pending, enqueue, flush, overlay, pendingFor } from '../queue';
import {
  Banner, Btn, Card, H, Label, Loading, Muted, Pill, Screen,
} from '../components/ui';
import { RA, S, T, TAP, tint, useTheme } from '../theme';

/** The order sections appear in, and the only place that order is decided.
 *
 *  REQUIRED'S BLURB USED TO READ "Race rules, darkness, or distance." Four
 *  words of trail running printed over an expedition to an uninhabited island
 *  with no organiser, no darkness rule and no distance — under a list whose
 *  entries were a leader and a braid. Found by reading the screen, which is
 *  where the other ten hardcoded activities were found too.
 *
 *  The other four blurbs describe what the CLASSIFICATION means rather than
 *  what a trail race is, so they were already right for both activities and
 *  are untouched. Only this one named a discipline, and naming the source of a
 *  requirement is genuinely useful — so it stays specific and becomes a
 *  function of the activity rather than going vague for everybody. */
const SECTIONS: { key: Classification; title: string; blurb: string }[] = [
  { key: 'missing', title: 'Missing',
    blurb: 'Required, and nothing in your locker fits.' },
  { key: 'required', title: 'Required',
    blurb: '' },   // per-activity, see REQUIRED_BLURB
  { key: 'recommended', title: 'Recommended',
    blurb: 'The conditions argue for these.' },
  { key: 'optional', title: 'Optional',
    blurb: 'Yours; no rule argues either way.' },
  { key: 'not_needed', title: 'Leave at home',
    blurb: 'A rule actively says these can stay.' },
];

const REQUIRED_BLURB: Record<string, string> = {
  trail_running: 'Race rules, darkness, or distance.',
  fishing: 'What the water, the target and the distance from help demand.',
};

/** Falls back to something true of any activity rather than to trail running.
 *  The next activity to be built gets a correct sentence before anyone
 *  remembers to add a line above — which is the failure this whole phase kept
 *  finding. */
const REQUIRED_BLURB_FALLBACK = 'Non-negotiable for this trip.';

/** Tapping cycles forward. Four states, one target, no menu — this gets used
 *  in a hallway at 5am with a bag open, not at a desk. Long-press steps back
 *  so a mis-tap costs one gesture rather than three. */
const CYCLE: PackState[] = ['not_selected', 'selected', 'packed', 'verified'];

const STATE_LABEL: Record<PackState, string> = {
  not_selected: '', selected: 'Selected', packed: 'Packed', verified: 'Verified',
  in_use: 'In use', returned: 'Returned', missing: 'Missing', damaged: 'Damaged',
};

export default function Pack({ adventureId, title, onAsk, onBack }: {
  adventureId: string;
  title: string;
  onAsk: () => void;
  onBack: () => void;
}) {
  const { P } = useTheme();
  const pack = useCached<PackT>(`pack.${adventureId}`, () => getPack(adventureId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLeave, setShowLeave] = useState(false);
  const [queued, setQueued] = useState<Pending[]>([]);

  // Send anything left over from a previous session, then read what is still
  // waiting. Both on mount, because that is the moment signal usually comes
  // back — the phone came out of a pocket at the finish.
  React.useEffect(() => {
    let alive = true;
    (async () => {
      const result = await flush();
      if (!alive) return;
      setQueued(await pendingFor(adventureId));
      // Only refresh when something actually reached the server, so a plain
      // screen open on a dead connection does not fire a doomed request.
      if (result.sent > 0) pack.refresh();
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adventureId]);

  // THE SERVER'S ANSWER IS NOT THE TRUTH WHILE A WRITE IS STILL WAITING.
  // Without this, reopening the screen while still offline shows the states the
  // server last knew about — the app forgetting what you just did, which is
  // worse than never having queued it.
  const data = useMemo(() => {
    if (!pack.data || !queued.length) return pack.data;
    return recount({ ...pack.data, items: overlay(pack.data.items, queued) });
  }, [pack.data, queued]);

  const grouped = useMemo(() => {
    const map = new Map<Classification, PackItem[]>();
    for (const item of data?.items ?? []) {
      const list = map.get(item.classification) ?? [];
      list.push(item);
      map.set(item.classification, list);
    }
    return map;
  }, [data?.items]);

  const regenerate = async () => {
    setBusy(true);
    setError(null);
    try {
      const fresh = await generatePack(adventureId);
      pack.set(fresh);
    } catch (e: any) {
      setError(e?.message ?? 'Could not build the pack.');
    } finally {
      setBusy(false);
    }
  };

  const cycle = async (item: PackItem, backwards = false) => {
    if (item.classification === 'missing') return;   // nothing to pack
    const at = CYCLE.indexOf(item.state);
    const from = at === -1 ? 0 : at;
    const next = CYCLE[(from + (backwards ? CYCLE.length - 1 : 1)) % CYCLE.length];

    // Optimistic. The tap has to feel instant with a bag open, and the failure
    // path re-reads from the server rather than guessing what went wrong.
    const optimistic = {
      ...data!,
      items: data!.items.map(i => (i.id === item.id ? { ...i, state: next } : i)),
    };
    pack.set(recount(optimistic));
    try {
      await setPackItemState(adventureId, item.id, next);
    } catch (e: any) {
      // NO SIGNAL IS NOT A FAILED WRITE. Reverting here — which is what the
      // refresh below used to do unconditionally — meant a tap in a car park
      // with no bars undid itself, on the one screen §20 names as the one that
      // has to work offline. A dropped connection queues; a server that
      // answered and refused is a real error and still says so.
      if (typeof e?.status !== 'number') {
        await enqueue(adventureId, item.id, next);
        setQueued(await pendingFor(adventureId));
      } else {
        setError(e?.message ?? 'That did not save.');
        await pack.refresh();
      }
    }
  };

  const sync = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await flush();
      setQueued(await pendingFor(adventureId));
      if (result.sent > 0) await pack.refresh();
      if (result.left > 0) setError('Still no connection — they are kept.');
      if (result.dropped > 0) {
        setError(`${result.dropped} change(s) could not be applied — those `
                 + `items have changed on the server.`);
        await pack.refresh();
      }
    } finally {
      setBusy(false);
    }
  };

  if (pack.loading) return <Loading label="Opening your pack…" />;

  if (!data?.list) {
    return (
      <Screen>
        <H>{title}</H>
        <Card style={{ gap: S[3] }}>
          <Label>No pack yet</Label>
          <Text style={[T.body, { color: P.textSec }]}>
            Smart Pack reads this adventure, your locker and the forecast, and
            sorts what you own into what you must carry, what the conditions
            argue for, and what you can leave. Every line says which rule put it
            there.
          </Text>
          {!!error && <Banner tone="error" text={error} />}
          <Btn label="Build the pack" onPress={regenerate} busy={busy} />
        </Card>
        <Btn kind="quiet" label="Back" onPress={onBack} />
      </Screen>
    );
  }

  const r = data.readiness;

  return (
    <Screen>
      <H>{title}</H>
      {pack.stale && <Banner text="Saved copy — reconnecting." />}
      {!!error && <Banner tone="error" text={error} />}

      {/* Said plainly, with a way to act on it. A pack that quietly holds
          unsent changes is a pack somebody arrives at a kit check believing is
          synced — and the states are on THIS phone, which is the one they are
          holding, so nothing is lost either way. */}
      {queued.length > 0 && (
        <Card style={{ gap: S[3] }}>
          <Label>Waiting for signal</Label>
          <Text style={[T.body, { color: P.textSec }]}>
            {queued.length} change{queued.length === 1 ? '' : 's'} saved on this
            phone and not sent yet. The list above is up to date; they will go
            when you are back in range.
          </Text>
          <Btn kind="quiet" label="Try now" onPress={sync} busy={busy} />
        </Card>
      )}

      <Readiness readiness={r} />

      <Tackle adventureId={adventureId} />

      <KitProvenance adventureId={adventureId}
                     hasRaceKit={data.items.some(i => i.source === 'mandatory')} />

      <Narrative adventureId={adventureId} />

      {data.warnings.length > 0 && (
        <Card style={{ gap: S[3] }}>
          <Label>Worth knowing</Label>
          {data.warnings.map(w => <WarningRow key={w.id} warning={w} />)}
        </Card>
      )}

      {SECTIONS.map(section => {
        const items = grouped.get(section.key) ?? [];
        if (!items.length) return null;
        if (section.key === 'not_needed' && !showLeave) {
          return (
            <Btn key={section.key} kind="quiet"
                 label={`Show ${items.length} you can leave at home`}
                 onPress={() => setShowLeave(true)} />
          );
        }
        return (
          <Card key={section.key} style={{ gap: S[3] }}>
            <View style={{ gap: S[1] }}>
              <View style={{ flexDirection: 'row', alignItems: 'center',
                             justifyContent: 'space-between' }}>
                <Label>{section.title}</Label>
                <Muted>{items.length}</Muted>
              </View>
              <Muted>
                {section.key === 'required'
                  ? (REQUIRED_BLURB[data.activity_key ?? '']
                     ?? REQUIRED_BLURB_FALLBACK)
                  : section.blurb}
              </Muted>
            </View>
            {items.map(item => (
              <ItemRow key={item.id} item={item}
                       onPress={() => cycle(item)}
                       onLongPress={() => cycle(item, true)} />
            ))}
          </Card>
        );
      })}

      <View style={{ gap: S[3], paddingTop: S[2] }}>
        {/* Placed here, at the bottom of the list, because that is where the
            question arrives — after reading the pack, not before it. */}
        <Btn kind="ghost" label="Ask about this pack" onPress={onAsk} />
        <Btn kind="quiet" label="Rebuild from the rules" busy={busy}
             onPress={() => Alert.alert(
               'Rebuild this pack?',
               'The rules run again against the current forecast and locker. Anything you have already selected, packed or verified stays as it is.',
               [{ text: 'Cancel', style: 'cancel' },
                { text: 'Rebuild', onPress: regenerate }])} />
        {!!data.list && (
          <Muted>
            {data.list.ruleset_version} · {data.items.length} lines ·
            {' '}{data.list.generation_snapshot?.weather?.days ?? 0} forecast day(s)
          </Muted>
        )}
      </View>
    </Screen>
  );
}

/** The written explanation of a pack that was decided without it.
 *
 *  THE CARD IS BUILT AROUND ONE RULE: the paragraph never replaces the list. It
 *  sits under the readiness figure and above the sections, adds nothing to
 *  them, and every number in it came from the engines. If this whole card fails
 *  to load — no key, budget spent, Anthropic down — the pack above and below it
 *  is unchanged, which is why the failure is a quiet line and not a red banner.
 *
 *  Generation is a TAP, never a mount. A screen that wrote a paragraph every
 *  time it appeared would spend a day's budget on scrolling. */
function Narrative({ adventureId }: { adventureId: string }) {
  const { P } = useTheme();
  const cached = useCached<NarrativeT>(`narrative.${adventureId}`,
                                       () => getNarrative(adventureId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const write = async () => {
    setBusy(true);
    setError(null);
    try {
      cached.set(await writeNarrative(adventureId));
    } catch (e: any) {
      setError(e?.message ?? 'Could not write that.');
    } finally {
      setBusy(false);
    }
  };

  const n = cached.data;
  if (cached.loading) return null;

  if (!n?.narrative) {
    return (
      <Card style={{ gap: S[3] }}>
        <Label>In words</Label>
        <Muted>
          A short read of this pack — where you stand and what the conditions
          mean. The list itself is worked out by the rules either way.
        </Muted>
        {!!error && <Muted>{error}</Muted>}
        <Btn kind="ghost" label="Explain this pack" onPress={write} busy={busy} />
      </Card>
    );
  }

  return (
    <Card style={{ gap: S[3] }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between',
                     alignItems: 'center' }}>
        <Label>In words</Label>
        {n.stale && <Pill label="Out of date" tone={P.warningInk} />}
      </View>

      <Text style={[T.body, { color: P.textPri, lineHeight: 22 }]}>
        {n.narrative}
      </Text>

      {/* Said plainly rather than hidden behind an icon. Everything else on
          this screen is computed and repeatable; this paragraph is not, and
          someone deciding what to trust at 5am deserves to know which is
          which. */}
      <Muted>
        {n.stale
          ? 'Written before you changed the pack — the numbers above are current.'
          : `Written by ${n.model ?? 'the AI'} from the list above. The pack itself is computed.`}
      </Muted>

      {!!error && <Muted>{error}</Muted>}
      <Btn kind="quiet" label={n.stale ? 'Write it again' : 'Refresh'}
           onPress={write} busy={busy} />
    </Card>
  );
}

/**
 * Does your tackle agree with itself? (§11, Phase 7)
 *
 * THE SECOND RULE SHAPE, on screen. Everything else on this page is one item
 * judged against the trip. These verdicts are about PAIRS — the reel and the
 * line, the line and the leader — which is the question that breaks tackle and
 * which a running race never has to ask.
 *
 * Renders nothing at all for a non-fishing adventure: the endpoint answers 409,
 * and a card saying "no tackle problems" over a trail race would be answering a
 * question nobody asked.
 */
function Tackle({ adventureId }: { adventureId: string }) {
  const { P } = useTheme();
  const [report, setReport] = useState<TackleReport | null>(null);

  React.useEffect(() => {
    let alive = true;
    getAdventureTackle(adventureId)
      .then(r => { if (alive) setReport(r); })
      .catch(() => { /* 409 = not a fishing trip. Offline = nothing to add. */ });
    return () => { alive = false; };
  }, [adventureId]);

  if (!report || !report.setups.length) return null;

  return (
    <Card style={{ gap: S[4] }}>
      <View style={{ gap: S[1] }}>
        <Label>Tackle</Label>
        <Muted>
          Whether the parts work together — rod against line, reel against line,
          leader against main. Standard practice, assumed rather than measured.
        </Muted>
      </View>

      {report.setups.map((setup, i) => {
        const parts = Object.entries(setup.parts)
          .filter(([role]) => role !== 'rod')
          .map(([role, item]) => item?.name)
          .filter(Boolean);
        return (
          <View key={setup.rod?.id ?? i} style={{ gap: S[2] }}>
            <View style={{ flexDirection: 'row', alignItems: 'center',
                           gap: S[2], flexWrap: 'wrap' }}>
              <Text style={[T.title, { color: P.textPri }]}>
                {setup.rod?.name ?? 'Setup'}
              </Text>
              {setup.problems > 0 && (
                <View style={{ paddingHorizontal: S[2], paddingVertical: 1,
                               borderRadius: RA.pill,
                               backgroundColor: tint(P.critical, 0.16) }}>
                  <Text style={[T.label, { color: P.critical }]}>
                    {setup.problems} PROBLEM{setup.problems === 1 ? '' : 'S'}
                  </Text>
                </View>
              )}
            </View>
            {parts.length > 0 && <Muted>with {parts.join(' · ')}</Muted>}
            {setup.verdicts.map(v => (
              <View key={v.rule_key}
                    style={{ flexDirection: 'row', gap: S[3] }}>
                <View style={{ width: 3, borderRadius: 2,
                               backgroundColor:
                                 v.state === 'not_recommended' ? P.critical
                                 : v.state === 'possibly_compatible' ? P.warningInk
                                 : v.state === 'unknown' ? P.textMuted
                                 : P.success }} />
                <Text style={[T.caption, { color: P.textSec, flex: 1 }]}>
                  {v.message}
                </Text>
              </View>
            ))}
          </View>
        );
      })}

      {/* §0.5, said where somebody can act on it. These are standard tackle
          practice, not measurements from this gear. */}
      <Muted>{report.note}</Muted>
    </Card>
  );
}

/** Where the mandatory kit came from (§24).
 *
 *  Shown only when the pack actually has race-kit lines on it, because that is
 *  when the question arises: eleven critical items nobody can trace back to a
 *  source is a list you either trust completely or not at all. Fetched lazily
 *  and silently — a missing provenance record means the kit was typed in by
 *  hand, which is a legitimate answer and not an error to report. */
function KitProvenance({ adventureId, hasRaceKit }: {
  adventureId: string; hasRaceKit: boolean;
}) {
  const [row, setRow] = useState<RaceKitDraft | null>(null);

  React.useEffect(() => {
    if (!hasRaceKit) return;
    let alive = true;
    getKitProvenance(adventureId)
      .then(r => { if (alive) setRow(r); })
      .catch(() => { /* typed by hand, or offline. Neither is worth a banner. */ });
    return () => { alive = false; };
  }, [adventureId, hasRaceKit]);

  if (!hasRaceKit || !row) return null;

  const where = row.source_kind === 'url'
    ? (row.source_url ?? 'a race page')
    : 'text you pasted';
  const when = (row.accepted_at ?? row.fetched_at ?? '').slice(0, 10);

  return (
    <Card style={{ gap: S[1] }}>
      <Label>Mandatory kit</Label>
      <Muted>
        {[row.race_name, row.edition, row.event].filter(Boolean).join(' · ') ||
         'Imported'}
      </Muted>
      <Muted>Read from {where}{when ? ` on ${when}` : ''}, and confirmed by you.</Muted>
    </Card>
  );
}

/** The readiness figure is recomputed locally after an optimistic tap so the
 *  number moves with the row. It mirrors engines/pack.readiness — the SERVER
 *  is authoritative and the next refresh corrects any drift; this exists so
 *  the count does not lag the gesture that changed it. */
function recount(pack: PackT): PackT {
  const required = pack.items.filter(i => i.classification === 'required');
  const packed = required.filter(i => i.state === 'packed' || i.state === 'verified');
  const critical = pack.items.filter(i => i.critical);
  const criticalUnverified = critical.filter(i => i.state !== 'verified');
  const missing = pack.items.filter(i => i.classification === 'missing');
  return {
    ...pack,
    readiness: {
      required_total: required.length,
      required_packed: packed.length,
      required_verified: required.filter(i => i.state === 'verified').length,
      remaining: required.length - packed.length,
      critical_total: critical.length,
      critical_unverified: criticalUnverified.length,
      missing_total: missing.length,
      percent: required.length
        ? Math.round((100 * packed.length) / required.length) : null,
      ready: required.length > 0 && missing.length === 0
             && packed.length === required.length
             && criticalUnverified.length === 0,
    },
  };
}

function Readiness({ readiness: r }: { readiness: PackT['readiness'] }) {
  const { P } = useTheme();
  // §9: a calm interface. The bar is brand-coloured while you work and only
  // turns green when everything genuinely holds — including the critical
  // items, which is the check that actually stops people at a kit table.
  const tone = r.ready ? P.success : P.brand;
  const pct = r.percent ?? 0;

  return (
    <Card style={{ gap: S[3] }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between',
                     alignItems: 'baseline' }}>
        <Label>Readiness</Label>
        <Text style={[T.h2, { color: r.percent === null ? P.textMuted : tone }]}>
          {r.percent === null ? '—' : `${r.percent}%`}
        </Text>
      </View>

      <View style={{ height: 8, borderRadius: 4, backgroundColor: P.sunken,
                     overflow: 'hidden' }}>
        <View style={{ height: 8, width: `${pct}%`, backgroundColor: tone }} />
      </View>

      <Text style={[T.body, { color: P.textPri }]}>
        {r.required_total === 0
          ? 'Nothing required yet.'
          : `Packed ${r.required_packed}/${r.required_total} · ${r.remaining} remaining`}
      </Text>

      {/* Reported separately rather than folded into the percentage. "43 of 47
          packed" and "one critical item unverified" are different facts, and
          the second is the one that ends a race at a kit check. */}
      {r.critical_unverified > 0 && (
        <Text style={[T.caption, { color: P.warningInk }]}>
          {r.critical_unverified} critical item
          {r.critical_unverified === 1 ? '' : 's'} not verified
        </Text>
      )}
      {r.missing_total > 0 && (
        <Text style={[T.caption, { color: P.critical }]}>
          {r.missing_total} required item{r.missing_total === 1 ? '' : 's'} you
          {' '}do not own
        </Text>
      )}
    </Card>
  );
}

function WarningRow({ warning }: { warning: PackWarningRow }) {
  const { P } = useTheme();
  const colour = warning.severity === 'critical' ? P.critical
    : warning.severity === 'caution' ? P.warningInk : P.textMuted;
  return (
    <View style={{ flexDirection: 'row', gap: S[3] }}>
      <View style={{ width: 3, borderRadius: 2, backgroundColor: colour }} />
      <Text style={[T.caption, { color: P.textSec, flex: 1 }]}>
        {warning.message}
      </Text>
    </View>
  );
}

function ItemRow({ item, onPress, onLongPress }: {
  item: PackItem; onPress: () => void; onLongPress: () => void;
}) {
  const { P } = useTheme();
  const missing = item.classification === 'missing';
  const done = item.state === 'packed' || item.state === 'verified';
  const accent = missing ? P.critical
    : item.state === 'verified' ? P.success
    : item.state === 'packed' ? P.brand : P.hairlineStrong;

  return (
    <Pressable
      onPress={onPress}
      onLongPress={onLongPress}
      disabled={missing}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: done, disabled: missing }}
      accessibilityLabel={`${item.name}. ${item.reason ?? ''} ${STATE_LABEL[item.state]}`}
      style={({ pressed }) => ({
        minHeight: TAP, flexDirection: 'row', alignItems: 'center', gap: S[3],
        paddingVertical: S[2], opacity: pressed ? 0.75 : 1,
      })}>
      {/* The box is the state. Deliberately not a colour change on the whole
          row: §19 asks for a calm interface, and a list where every packed
          line turns green is a list you stop reading. */}
      <View style={{
        width: 24, height: 24, borderRadius: 7, borderWidth: 2,
        borderColor: accent, alignItems: 'center', justifyContent: 'center',
        backgroundColor: done ? accent : 'transparent',
      }}>
        {item.state === 'verified' && (
          <Text style={{ color: P.onBrand, fontSize: 13, fontWeight: '700' }}>✓✓</Text>
        )}
        {item.state === 'packed' && (
          <Text style={{ color: P.onBrand, fontSize: 14, fontWeight: '700' }}>✓</Text>
        )}
        {item.state === 'selected' && (
          <View style={{ width: 10, height: 10, borderRadius: 3,
                         backgroundColor: accent }} />
        )}
      </View>

      <View style={{ flex: 1, gap: 2 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: S[2],
                       flexWrap: 'wrap' }}>
          <Text style={[T.body, {
            color: missing ? P.textPri : P.textPri,
            textDecorationLine: item.state === 'verified' ? 'line-through' : 'none',
          }]}>
            {item.name}
          </Text>
          {item.critical && (
            <View style={{ paddingHorizontal: S[2], paddingVertical: 1,
                           borderRadius: RA.pill,
                           backgroundColor: tint(P.critical, 0.16) }}>
              <Text style={[T.label, { color: P.critical }]}>CRITICAL</Text>
            </View>
          )}
          {item.source === 'mandatory' && <Pill label="Race kit" />}
        </View>
        {!!item.reason && <Muted>{item.reason}</Muted>}
      </View>

      {!missing && !!STATE_LABEL[item.state] && (
        <Text style={[T.caption, { color: accent }]}>{STATE_LABEL[item.state]}</Text>
      )}
      {missing && <Text style={[T.caption, { color: P.critical }]}>Not owned</Text>}
    </Pressable>
  );
}
