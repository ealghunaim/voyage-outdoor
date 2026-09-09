import React, { useMemo } from 'react';
import { Pressable, Text, View } from 'react-native';

import {
  Adventure, AttentionItem, GearItem, gearNeedingAttention, listAdventures,
  listGear,
} from '../api';
import { useCached } from '../cache';
import {
  Banner, Btn, Card, Label, Loading, Muted, Pill, Row, Screen,
} from '../components/ui';
import { day, titleCase, weight } from '../format';
import { S, T, useTheme } from '../theme';

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return 'Still up';
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export default function Home({ onOpenGear, onAddGear, onGearTab,
                               onOpenAdventure, onPlanAdventure }: {
  onOpenGear: (id: string) => void;
  onAddGear: () => void;
  onGearTab: () => void;
  onOpenAdventure: (id: string) => void;
  onPlanAdventure: () => void;
}) {
  const { P } = useTheme();
  const gear = useCached<GearItem[]>('gear.active', () => listGear({ status: 'active' }));
  const adventures = useCached<Adventure[]>('adventures.live', () => listAdventures());
  const attention = useCached<{ items: AttentionItem[]; checked: number }>(
    'gear.attention', gearNeedingAttention);

  /** The soonest one that has not finished. Not simply the first row: the list
   *  arrives ordered by start date, and an adventure that started yesterday
   *  and ends tomorrow is more "next" than one three weeks out. */
  const next = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return (adventures.data ?? [])
      .filter(a => a.end_date >= today && a.status !== 'completed')
      .sort((a, b) => a.start_date.localeCompare(b.start_date))[0] ?? null;
  }, [adventures.data]);

  // Memoised on gear.data rather than on a `?? []` expression: the fallback
  // array is a new object every render, so it would invalidate the memo every
  // time and make memoising it pointless.
  const items = useMemo(() => gear.data ?? [], [gear.data]);

  const summary = useMemo(() => {
    const byCategory = new Map<string, number>();
    let totalWeight = 0;
    for (const g of items) {
      if (g.category_key) byCategory.set(g.category_key, (byCategory.get(g.category_key) ?? 0) + 1);
      totalWeight += g.weight_g ?? 0;
    }
    return { count: items.length, categories: byCategory.size, totalWeight };
  }, [items]);

  const recent = items.slice(0, 4);

  if (gear.loading) return <Loading />;

  return (
    <Screen>
      <View style={{ paddingTop: S[2], gap: S[1] }}>
        <Text style={[T.display, { color: P.textPri }]}>{greeting()}</Text>
        <Muted>Trail running · Voyage Outdoor</Muted>
      </View>

      {gear.stale && <Banner text="Saved copy — reconnecting." />}

      {/* NEXT ADVENTURE — §17's first card. Empty is a real state, not a
          placeholder: someone with nothing planned should be invited to plan
          something rather than shown a fabricated example. */}
      {next ? (
        <Card onPress={() => onOpenAdventure(next.id)}>
          <View style={{ gap: S[2] }}>
            <Label>Next adventure</Label>
            <Text style={[T.h2, { color: P.textPri }]}>{next.title}</Text>
            <View style={{ flexDirection: 'row', gap: S[2], flexWrap: 'wrap',
                           alignItems: 'center' }}>
              <Pill label={day(next.start_date)} tone={P.brand} />
              {!!next.attributes?.distance_km &&
                <Pill label={`${next.attributes.distance_km} km`} />}
              {!!next.attributes?.elevation_gain_m &&
                <Pill label={`${next.attributes.elevation_gain_m} m+`} />}
            </View>
            {!!next.place_name && <Muted>{next.place_name}</Muted>}
          </View>
        </Card>
      ) : (
        <Card style={{ gap: S[3] }}>
          <Label>Next adventure</Label>
          <Text style={[T.body, { color: P.textSec }]}>
            Nothing planned. An adventure is what everything else works from —
            what to pack, which shoes, what the weather is doing.
          </Text>
          <Btn kind="ghost" label="Plan an adventure" onPress={onPlanAdventure} />
        </Card>
      )}

      <Card style={{ gap: S[1] }}>
        <Label>Gear locker</Label>
        <Row label="Items" value={String(summary.count)} />
        <Row label="Categories" value={String(summary.categories)} />
        <Row label="Total weight" value={summary.totalWeight ? weight(summary.totalWeight) : '—'} />
        <View style={{ paddingTop: S[3] }}>
          <Btn kind="ghost" label="Open locker" onPress={onGearTab} />
        </View>
      </Card>

      {/* GEAR NEEDING ATTENTION — §17, and §12 on how it may be phrased.
          Every line is the engine's own sentence: a band and a prompt to
          inspect, never a prediction of when something will fail. */}
      <Card style={{ gap: S[2] }}>
        <Label>Needing attention</Label>
        {(attention.data?.items.length ?? 0) === 0 ? (
          <Muted>
            {attention.data?.checked
              ? `Nothing flagged across ${attention.data.checked} items.`
              : 'Nothing to check yet — log some runs and wear shows up here.'}
          </Muted>
        ) : (
          <View style={{ gap: S[3] }}>
            {attention.data!.items.map(i => (
              <Pressable key={i.id} onPress={() => onOpenGear(i.id)}
                         style={{ gap: 2 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center',
                               gap: S[2] }}>
                  <Text style={[T.body, { color: P.textPri }]}>{i.name}</Text>
                  <Pill label={i.state === 'past_expected' ? 'Past range' : 'Inspect'}
                        tone={i.state === 'past_expected' ? P.critical : P.warningInk} />
                </View>
                <Muted>{i.message}</Muted>
              </Pressable>
            ))}
          </View>
        )}
      </Card>

      {recent.length > 0 ? (
        <Card style={{ gap: S[2] }}>
          <Label>Recent gear</Label>
          {recent.map(g => (
            <Row key={g.id}
                 label={g.name}
                 value={`${g.category_key ? titleCase(g.category_key) : ''}`} />
          ))}
          <View style={{ paddingTop: S[3] }}>
            <Btn kind="quiet" label="Add gear" onPress={onAddGear} />
          </View>
        </Card>
      ) : (
        <Card style={{ gap: S[3] }}>
          <Label>Start here</Label>
          <Text style={[T.body, { color: P.textSec }]}>
            Add the gear you already own — shoes, vest, poles, headlamp. Everything
            this app does later starts from knowing what is in your locker.
          </Text>
          <Btn label="Add your first item" onPress={onAddGear} />
        </Card>
      )}
    </Screen>
  );
}
