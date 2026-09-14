import React, { useMemo, useState } from 'react';
import { Alert, Pressable, Text, View } from 'react-native';

import {
  ActivitySchema, GearDetail as GearDetailT, Review, UsageKind, deleteGear,
  getActivitySchema, getGear, getReview, logUsage, putReview, updateGear,
} from '../api';
import { dropCache, useCached } from '../cache';
import { describeAttributes } from '../components/AttributeFields';
import {
  Banner, Btn, Card, Field, H, Label, Loading, Muted, Pill, Row, Screen,
} from '../components/ui';
import { day, distance, duration, since, titleCase, weight } from '../format';
import { S, T, TAP, useTheme } from '../theme';

export default function GearDetail({ gearId, onEdit, onGone }: {
  gearId: string;
  onEdit: () => void;
  onGone: () => void;
}) {
  const { P } = useTheme();
  const item = useCached<GearDetailT>(`gear.${gearId}`, () => getGear(gearId));
  // THE ITEM'S OWN ACTIVITY, not a constant. A rod and a running shoe have
  // different field sets, different usage kinds and different sizing, and
  // asking the trail-running schema about a reel returns nothing at all — the
  // specs card would simply be empty, which reads as "no specs recorded".
  //
  // Null until the item loads: useCached treats a null key as "not ready" and
  // fetches nothing, rather than fetching the wrong schema and replacing it.
  const item0 = item.data;
  const schema = useCached<ActivitySchema>(
    item0?.activity_key ? `schema.${item0.activity_key}` : null,
    () => getActivitySchema(item0!.activity_key!));

  const [logging, setLogging] = useState(false);
  const [logDistance, setLogDistance] = useState('');
  const [logDate, setLogDate] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const g = item.data;

  const specs = useMemo(() => {
    if (!g || !schema.data) return [];
    const fields = g.category_key ? schema.data.gear[g.category_key] ?? {} : {};
    return describeAttributes(fields, g.attributes ?? {});
  }, [g, schema.data]);

  // What this category actually accumulates. Defaults to 'sessions' rather
  // than 'distance' — until the schema has loaded, or for a category the
  // server has not heard of, the safe assumption is the one that asks the
  // user for nothing they would have to measure.
  const usage: UsageKind = (g?.category_key && schema.data?.usage?.[g.category_key])
    || 'sessions';
  const tracksDistance = usage === 'distance';

  const invalidate = async () => {
    await Promise.all([dropCache('gear.active'), dropCache('gear.all')]);
  };

  const addUsage = async () => {
    setError(null);
    setBusy(true);
    try {
      const km = parseFloat(logDistance);
      await logUsage(gearId, {
        occurred_on: logDate,
        distance_m: Number.isFinite(km) ? Math.round(km * 1000) : null,
      });
      setLogging(false);
      setLogDistance('');
      await item.refresh();
      await invalidate();
    } catch (e: any) {
      setError(e?.message ?? 'Could not log that.');
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (status: 'active' | 'retired') => {
    setBusy(true);
    try {
      await updateGear(gearId, { status });
      await item.refresh();
      await invalidate();
    } catch (e: any) {
      setError(e?.message ?? 'Could not update that.');
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = () => {
    Alert.alert(
      'Delete this gear?',
      'Its usage and maintenance history go with it. Retiring keeps the record and takes it out of your active locker.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Retire instead', onPress: () => setStatus('retired') },
        {
          text: 'Delete', style: 'destructive',
          onPress: async () => {
            try {
              await deleteGear(gearId);
              await Promise.all([invalidate(), dropCache(`gear.${gearId}`)]);
              onGone();
            } catch (e: any) {
              setError(e?.message ?? 'Could not delete that.');
            }
          },
        },
      ],
    );
  };

  if (item.loading) return <Loading label="Loading…" />;
  if (!g) {
    return (
      <Screen>
        <Banner tone="error" text={item.error ?? 'That gear is not available offline.'} />
        <Btn kind="quiet" label="Back" onPress={onGone} />
      </Screen>
    );
  }

  const retired = g.status !== 'active';

  return (
    <Screen>
      {item.stale && <Banner text="Saved copy — reconnecting." />}
      {!!error && <Banner tone="error" text={error} />}

      <View style={{ gap: S[2] }}>
        <H>{g.name}</H>
        <View style={{ flexDirection: 'row', gap: S[2], flexWrap: 'wrap' }}>
          {!!g.category_key && <Pill label={titleCase(g.category_key)} />}
          {retired && <Pill label={g.status} tone={P.textMuted} filled />}
          {g.favorite && <Pill label="Favourite" tone={P.warning} />}
        </View>
        {!!(g.brand || g.model) && (
          <Text style={[T.body, { color: P.textSec }]}>
            {[g.brand, g.model].filter(Boolean).join(' ')}
          </Text>
        )}
      </View>

      <Card style={{ gap: S[1] }}>
        <Label>Use</Label>
        {/* Distance only where the category accumulates one. A life jacket
            reading "0 km" is not a fact about the life jacket — it is the
            screen asking a question that does not apply to it. */}
        {tracksDistance && (
          <Row label="Total distance" value={distance(g.totals.distance_m)} />
        )}
        <Row label={tracksDistance ? 'Sessions' : 'Times used'}
             value={String(g.totals.sessions)} />
        {g.totals.duration_s > 0 && (
          <Row label="Time" value={duration(g.totals.duration_s)} />
        )}
        <Row label="Last used" value={since(g.totals.last_used_on)} />
        <Row
          label="Condition"
          // NOT computed here. §12: never present an uncertain estimate as a
          // fact, and a percentage invented at read time is exactly that. The
          // gear-health engine lands in Phase 3 and will write this column.
          value={g.condition_pct === null ? 'Not measured yet' : `${g.condition_pct}%`}
          tone={g.condition_pct === null ? P.textMuted : undefined}
        />
      </Card>

      {specs.length > 0 && (
        <Card style={{ gap: S[1] }}>
          <Label>Specifications</Label>
          {specs.map(s => <Row key={s.label} label={s.label} value={s.value} />)}
        </Card>
      )}

      <Card style={{ gap: S[1] }}>
        <Label>Record</Label>
        {/* Only when there is one. A blank "Size —" row on a headlamp is a
            question the record was never going to answer. */}
        {!!g.size && <Row label="Size" value={g.size} />}
        <Row label="Weight" value={weight(g.weight_g)} />
        <Row label="Bought" value={day(g.purchase_date)} />
        {!!g.notes && (
          <View style={{ paddingTop: S[2] }}>
            <Text style={[T.body, { color: P.textSec }]}>{g.notes}</Text>
          </View>
        )}
      </Card>

      {/* 'none' is a consumable — a gel accumulates nothing, so there is
          nothing to offer. Anything else logs, and only distance-tracked
          categories are asked for a distance. */}
      {usage !== 'none' && (logging ? (
        <Card style={{ gap: S[4] }}>
          <Label>{tracksDistance ? 'Log a run' : 'Log a use'}</Label>
          <Field label="Date" value={logDate} onChange={setLogDate} placeholder="YYYY-MM-DD" />
          {tracksDistance && (
            <Field label="Distance" unit="km" value={logDistance}
                   onChange={t => setLogDistance(t.replace(/[^0-9.]/g, ''))}
                   keyboardType="decimal-pad" placeholder="21.1" />
          )}
          <Btn label="Save" onPress={addUsage} busy={busy} />
          <Btn kind="quiet" label="Cancel" onPress={() => setLogging(false)} />
        </Card>
      ) : (
        <Btn kind="ghost" label={tracksDistance ? 'Log a run' : 'Log a use'}
             onPress={() => setLogging(true)} />
      ))}

      <ReviewCard gearId={gearId} />

      {g.usage.length > 0 && (
        <Card style={{ gap: S[2] }}>
          <Label>History</Label>
          {g.usage.slice(0, 10).map(u => (
            <Row key={u.id} label={day(u.occurred_on)}
                 // An em dash beside every date is noise. Where distance is not
                 // recorded the date IS the entry, so the row carries nothing
                 // on the right rather than a placeholder for a missing number.
                 value={u.distance_m !== null ? distance(u.distance_m) : ''} />
          ))}
          {g.usage.length > 10 && <Muted>{g.usage.length - 10} more</Muted>}
        </Card>
      )}

      {g.maintenance.length > 0 && (
        <Card style={{ gap: S[2] }}>
          <Label>Maintenance</Label>
          {g.maintenance.map(m => (
            <Row key={m.id} label={`${titleCase(m.kind)} · ${day(m.occurred_on)}`}
                 value={m.next_due_on ? `next ${day(m.next_due_on)}` : ''} />
          ))}
        </Card>
      )}

      <View style={{ gap: S[3], paddingTop: S[2] }}>
        <Btn label="Edit" onPress={onEdit} kind="quiet" />
        <Btn kind="quiet"
             label={retired ? 'Return to active locker' : 'Retire'}
             onPress={() => setStatus(retired ? 'active' : 'retired')} />
        <Btn kind="quiet" label="Delete" tone={P.danger} onPress={confirmDelete} />
      </View>
    </Screen>
  );
}

/**
 * Your review of this item (§14, §15).
 *
 * ON A LOCKER ITEM, NOT A CATALOG PRODUCT, and that follows from §0.4 rather
 * than being a shortcut: V1 has no live product database, so reviews of the
 * catalog would be a feature with almost nothing to point at. This item, you
 * own — which means the review has evidence behind it already.
 *
 * AND THE EVIDENCE IS THE FEATURE. A star rating on its own says nothing about
 * whether it was earned over one wet weekend or two seasons. The server
 * snapshots the record at the moment you write — distance, sessions,
 * adventures, the health band — and this card shows it, because that is what
 * makes the rating mean something a year later. It is frozen deliberately: a
 * live join would let a review written at 200 km silently start claiming 900.
 */
function ReviewCard({ gearId }: { gearId: string }) {
  const { P } = useTheme();
  const [review, setReview] = useState<Review | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [rating, setRating] = useState(0);
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    getReview(gearId)
      .then(r => { if (!alive) return; setReview(r); if (r) { setRating(r.rating); setBody(r.body ?? ''); } })
      .catch(() => { /* not reviewed, or offline. Neither is an error. */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [gearId]);

  const save = async () => {
    if (!rating) { setErr('Pick a rating first.'); return; }
    setBusy(true); setErr(null);
    try {
      setReview(await putReview(gearId, rating, body.trim() || null));
      setEditing(false);
    } catch (e: any) {
      setErr(e?.message ?? 'Could not save that.');
    } finally { setBusy(false); }
  };

  if (loading) return null;

  const c = review?.context;
  const bits = c ? [
    c.distance_m ? distance(c.distance_m) : null,
    `${c.sessions} session${c.sessions === 1 ? '' : 's'}`,
    c.adventures?.length ? `${c.adventures.length} adventure${c.adventures.length === 1 ? '' : 's'}` : null,
    c.maintenance_events ? `${c.maintenance_events} service${c.maintenance_events === 1 ? '' : 's'}` : null,
  ].filter(Boolean) as string[] : [];

  return (
    <Card style={{ gap: S[3] }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between',
                     alignItems: 'center' }}>
        <Label>Your review</Label>
        {!!review && !editing && <Muted>{day(review.updated_at)}</Muted>}
      </View>

      {!!err && <Muted>{err}</Muted>}

      {editing || !review ? (
        <View style={{ gap: S[4] }}>
          <Stars value={rating} onChange={setRating} />
          <Field label="What is it actually like?" value={body} onChange={setBody}
                 multiline
                 placeholder="Fit, durability, what it is good and bad at." />
          <Btn label={review ? 'Save changes' : 'Save review'} onPress={save}
               busy={busy} disabled={!rating} />
          {!!review && (
            <Btn kind="quiet" label="Cancel" onPress={() => {
              setEditing(false); setRating(review.rating); setBody(review.body ?? '');
            }} />
          )}
          {!review && (
            <Muted>
              Saved with what the record says right now — distance, sessions and
              condition — so it still means something in a year.
            </Muted>
          )}
        </View>
      ) : (
        <View style={{ gap: S[2] }}>
          <Stars value={review.rating} />
          {!!review.body && (
            <Text style={[T.body, { color: P.textPri }]}>{review.body}</Text>
          )}
          {/* WHAT IT WAS BASED ON, at the time. Without this a rating is an
              opinion; with it, it is a measurement someone can weigh. */}
          {bits.length > 0 && <Muted>Written after {bits.join(' · ')}.</Muted>}
          {!!c?.health_message && <Muted>Condition then: {c.health_message}</Muted>}
          <View style={{ paddingTop: S[2] }}>
            <Btn kind="quiet" label="Edit" onPress={() => setEditing(true)} />
          </View>
        </View>
      )}
    </Card>
  );
}

/** Five taps, no half stars. A scale finer than the judgement behind it invites
 *  precision nobody has. */
function Stars({ value, onChange }: { value: number; onChange?: (n: number) => void }) {
  const { P } = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: S[2] }}>
      {[1, 2, 3, 4, 5].map(n => (
        <Pressable
          key={n}
          disabled={!onChange}
          onPress={() => onChange?.(n)}
          hitSlop={8}
          accessibilityRole={onChange ? 'radio' : 'text'}
          accessibilityState={{ selected: n <= value }}
          accessibilityLabel={`${n} of 5`}
          style={{ minHeight: onChange ? TAP : undefined, justifyContent: 'center' }}>
          <Text style={{ fontSize: 26, color: n <= value ? P.brand : P.hairlineStrong }}>
            {n <= value ? '★' : '☆'}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
