import React, { useMemo, useState } from 'react';
import { SectionList, Text, View } from 'react-native';

import { Adventure, AdventureStatus, listAdventures } from '../api';
import { useCached } from '../cache';
import { Chevron } from '../components/icons';
import {
  Banner, Btn, Card, Empty, Label, Loading, Muted, Pill, Screen,
} from '../components/ui';
import { day, titleCase } from '../format';
import { S, T, useTheme } from '../theme';

/** How many days until it starts — the number that decides where a card sits
 *  and what it says. Negative means it has already started. */
function daysUntil(iso: string): number {
  const start = new Date(`${iso.slice(0, 10)}T00:00:00Z`).getTime();
  const today = new Date(new Date().toISOString().slice(0, 10) + 'T00:00:00Z').getTime();
  return Math.round((start - today) / 86_400_000);
}

function countdown(a: Adventure): string {
  if (a.status === 'completed') return 'Done';
  const d = daysUntil(a.start_date);
  if (d < 0 && a.end_date >= new Date().toISOString().slice(0, 10)) return 'Happening now';
  if (d < 0) return day(a.start_date);
  if (d === 0) return 'Today';
  if (d === 1) return 'Tomorrow';
  if (d < 31) return `In ${d} days`;
  if (d < 365) return `In ${Math.round(d / 30)} months`;
  return day(a.start_date);
}

export default function Adventures({ onOpen, onCreate }: {
  onOpen: (id: string) => void;
  onCreate: () => void;
}) {
  const { P } = useTheme();
  const [showArchived, setShowArchived] = useState(false);
  const list = useCached<Adventure[]>(
    `adventures.${showArchived ? 'all' : 'live'}`,
    () => listAdventures(showArchived ? { status: 'all' } : {}),
  );

  const items = useMemo(() => list.data ?? [], [list.data]);

  // Upcoming first and ascending — the next thing you are doing is the point
  // of this screen. Past adventures descend below it, most recent first,
  // because looking back you want the last one rather than the first.
  const { upcoming, past } = useMemo(() => {
    const up: Adventure[] = [], done: Adventure[] = [];
    for (const a of items) (daysUntil(a.end_date) >= 0 ? up : done).push(a);
    up.sort((x, y) => x.start_date.localeCompare(y.start_date));
    done.sort((x, y) => y.start_date.localeCompare(x.start_date));
    return { upcoming: up, past: done };
  }, [items]);

  if (list.loading) return <Loading label="Loading your adventures…" />;

  const header = (
    <View style={{ gap: S[3] }}>
      <View style={{ flexDirection: 'row', alignItems: 'center',
                     justifyContent: 'space-between', paddingTop: S[2] }}>
        <Text style={[T.display, { color: P.textPri }]}>Adventures</Text>
      </View>

      {list.stale && !list.error && <Banner text="Saved copy — reconnecting." />}
      {!!list.error && <Banner tone="warn" text={`${list.error} Showing what was saved.`} />}

      {items.length > 0 && <Btn label="Plan an adventure" onPress={onCreate} />}
    </View>
  );

  // SCROLL={FALSE}, and that is load-bearing rather than tidy: a SectionList
  // inside Screen's ScrollView is the nested-VirtualizedList anti-pattern —
  // React Native warns about it, and it virtualises nothing, because the outer
  // scroller gives the inner list unbounded height so every row stays mounted.
  // The header goes into ListHeaderComponent instead, which also lets it scroll
  // away with the content.
  return (
    <Screen scroll={false} padded={false}>
      <SectionList
        sections={[
          ...(upcoming.length ? [{ title: 'Upcoming', data: upcoming }] : []),
          ...(past.length ? [{ title: 'Past', data: past }] : []),
        ]}
        keyExtractor={a => a.id}
        renderItem={({ item, section }) => (
          <View style={{ paddingBottom: S[3] }}>
            <Row adventure={item} onPress={() => onOpen(item.id)}
                 past={section.title === 'Past'} />
          </View>
        )}
        renderSectionHeader={({ section }) => (
          <View style={{ paddingTop: S[2], paddingBottom: S[3] }}>
            <Label>{section.title}</Label>
          </View>
        )}
        // ADVENTURES ACCUMULATE. A season is thirty; five seasons is a hundred
        // and fifty, and none are ever deleted because the mileage hangs off
        // them. §28 asks for thousands rather than demo-data assumptions.
        initialNumToRender={10}
        windowSize={7}
        removeClippedSubviews
        stickySectionHeadersEnabled={false}
        ListHeaderComponent={header}
        ListEmptyComponent={
          <Empty
            title="No adventures yet"
            body="An adventure is what you are actually doing — a race, a long day out. Everything else works from it: what to pack, which shoes, what the weather is doing."
            action={<View style={{ minWidth: 220 }}>
              <Btn label="Plan an adventure" onPress={onCreate} />
            </View>}
          />
        }
        ListFooterComponent={
          items.length > 0 ? (
            <View style={{ paddingTop: S[2] }}>
              <Btn kind="quiet"
                   label={showArchived ? 'Hide archived' : 'Show archived'}
                   onPress={() => setShowArchived(s => !s)} />
            </View>
          ) : null
        }
        contentContainerStyle={{ padding: S[4], paddingBottom: S[12] }}
      />
    </Screen>
  );
}

const STATUS_TONE: Record<AdventureStatus, 'brand' | 'muted' | 'success'> = {
  draft: 'muted', planned: 'brand', active: 'success',
  completed: 'muted', archived: 'muted',
};

function Row({ adventure, onPress, past }: {
  adventure: Adventure; onPress: () => void; past?: boolean;
}) {
  const { P } = useTheme();
  const tone = STATUS_TONE[adventure.status];
  const colour = tone === 'brand' ? P.brand : tone === 'success' ? P.success : P.textMuted;
  const km = adventure.attributes?.distance_km;
  const gain = adventure.attributes?.elevation_gain_m;

  return (
    <Card onPress={onPress} style={{ opacity: past ? 0.75 : 1 }}
          accessibilityLabel={[adventure.title, countdown(adventure),
                               adventure.place_name,
                               km ? `${km} kilometres` : null]
                                .filter(Boolean).join(', ')}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: S[3] }}>
        <View style={{ flex: 1, gap: S[2] }}>
          <Text style={[T.title, { color: P.textPri }]} numberOfLines={1}>
            {adventure.title}
          </Text>
          <View style={{ flexDirection: 'row', gap: S[2], alignItems: 'center',
                         flexWrap: 'wrap' }}>
            <Pill label={countdown(adventure)} tone={colour} />
            {adventure.status !== 'planned' && adventure.status !== 'completed' && (
              <Pill label={titleCase(adventure.status)} />
            )}
          </View>
          <Muted>
            {[adventure.place_name,
              km ? `${km} km` : null,
              gain ? `${gain} m+` : null,
            ].filter(Boolean).join(' · ') || day(adventure.start_date)}
          </Muted>
        </View>
        <Chevron color={P.textMuted} />
      </View>
    </Card>
  );
}
