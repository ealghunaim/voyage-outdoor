import React, { useMemo, useState } from 'react';
import { Alert, Pressable, Text, View } from 'react-native';

import {
  Classification, Pack as PackT, PackItem, PackState, PackWarningRow,
  generatePack, getPack, setPackItemState,
} from '../api';
import { useCached } from '../cache';
import {
  Banner, Btn, Card, H, Label, Loading, Muted, Pill, Screen,
} from '../components/ui';
import { RA, S, T, TAP, tint, useTheme } from '../theme';

/** The order sections appear in, and the only place that order is decided. */
const SECTIONS: { key: Classification; title: string; blurb: string }[] = [
  { key: 'missing', title: 'Missing',
    blurb: 'Required, and nothing in your locker fits.' },
  { key: 'required', title: 'Required',
    blurb: 'Race rules, darkness, or distance.' },
  { key: 'recommended', title: 'Recommended',
    blurb: 'The conditions argue for these.' },
  { key: 'optional', title: 'Optional',
    blurb: 'Yours; no rule argues either way.' },
  { key: 'not_needed', title: 'Leave at home',
    blurb: 'A rule actively says these can stay.' },
];

/** Tapping cycles forward. Four states, one target, no menu — this gets used
 *  in a hallway at 5am with a bag open, not at a desk. Long-press steps back
 *  so a mis-tap costs one gesture rather than three. */
const CYCLE: PackState[] = ['not_selected', 'selected', 'packed', 'verified'];

const STATE_LABEL: Record<PackState, string> = {
  not_selected: '', selected: 'Selected', packed: 'Packed', verified: 'Verified',
  in_use: 'In use', returned: 'Returned', missing: 'Missing', damaged: 'Damaged',
};

export default function Pack({ adventureId, title, onBack }: {
  adventureId: string;
  title: string;
  onBack: () => void;
}) {
  const { P } = useTheme();
  const pack = useCached<PackT>(`pack.${adventureId}`, () => getPack(adventureId));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLeave, setShowLeave] = useState(false);

  const data = pack.data;

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
      setError(e?.message ?? 'That did not save.');
      await pack.refresh();
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

      <Readiness readiness={r} />

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
              <Muted>{section.blurb}</Muted>
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
