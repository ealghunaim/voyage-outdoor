import React, { useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { GearCategory, GearItem, listCategories, listGear } from '../api';
import { useCached } from '../cache';
import { Chevron, Star } from '../components/icons';
import { Banner, Btn, Card, Empty, Field, Loading, Muted, Pill } from '../components/ui';
import { titleCase, weight } from '../format';
import { RA, S, T, TAP, useTheme } from '../theme';

/** The locker list.
 *
 *  Cached under a key that describes the DATA, not the screen, so the detail
 *  screen's write-through and this list agree without either knowing about the
 *  other.
 */
export default function GearLocker({ onOpen, onAdd }: {
  onOpen: (id: string) => void;
  onAdd: () => void;
}) {
  const { P } = useTheme();
  const [category, setCategory] = useState<string | null>(null);
  const [showRetired, setShowRetired] = useState(false);
  const [q, setQ] = useState('');

  const gear = useCached<GearItem[]>(
    `gear.${showRetired ? 'all' : 'active'}`,
    () => listGear({ status: showRetired ? 'all' : 'active' }),
  );
  const categories = useCached<GearCategory[]>('categories.trail_running',
    () => listCategories('trail_running'));

  // Filtered on the client, deliberately. The server supports both filters, but
  // the whole locker is already in memory and on disk — round-tripping to
  // narrow a list of forty items would make the filter feel slower than the
  // list it filters, and would fail entirely with no signal.
  const items = useMemo(() => {
    let rows = gear.data ?? [];
    if (category) rows = rows.filter(g => g.category_key === category);
    if (q.trim()) {
      const needle = q.trim().toLowerCase();
      rows = rows.filter(g =>
        `${g.name} ${g.brand ?? ''} ${g.model ?? ''}`.toLowerCase().includes(needle));
    }
    return rows;
  }, [gear.data, category, q]);

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const g of gear.data ?? []) {
      if (!g.category_key) continue;
      map.set(g.category_key, (map.get(g.category_key) ?? 0) + 1);
    }
    return map;
  }, [gear.data]);

  // Only categories that hold something. A filter row of twenty empty
  // categories is twenty ways to reach an empty list.
  const usable = (categories.data ?? []).filter(c => counts.get(c.key));

  if (gear.loading) return <Loading label="Opening your locker…" />;

  return (
    <View style={{ flex: 1, backgroundColor: P.pageBg }}>
      <View style={{ padding: S[4], gap: S[3] }}>
        <Field label="Search" value={q} onChange={setQ} placeholder="Norda, vest, headlamp…" />
        {usable.length > 0 && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false}
                      contentContainerStyle={{ gap: S[2], paddingVertical: S[1] }}>
            <FilterChip label={`All ${gear.data?.length ?? 0}`}
                        on={category === null} onPress={() => setCategory(null)} />
            {usable.map(c => (
              <FilterChip key={c.key} label={`${c.name} ${counts.get(c.key)}`}
                          on={category === c.key}
                          onPress={() => setCategory(category === c.key ? null : c.key)} />
            ))}
          </ScrollView>
        )}
      </View>

      <ScrollView contentContainerStyle={{ padding: S[4], paddingTop: 0,
                                           paddingBottom: S[12], gap: S[3] }}>
        {gear.stale && !gear.error && (
          <Banner text="Showing your saved locker — reconnecting." />
        )}
        {!!gear.error && (
          <Banner tone="warn" text={`${gear.error} Showing what was saved.`} />
        )}

        {items.length === 0 ? (
          <Empty
            title={q || category ? 'Nothing matches' : 'Your locker is empty'}
            body={q || category
              ? 'Try a different filter.'
              : 'Add the gear you already own. Manual entry is the fast path — there is no product database to search yet.'}
            action={!q && !category
              ? <View style={{ minWidth: 200 }}><Btn label="Add gear" onPress={onAdd} /></View>
              : undefined}
          />
        ) : items.map(item => (
          <GearRow key={item.id} item={item} onPress={() => onOpen(item.id)} />
        ))}

        <Pressable onPress={() => setShowRetired(r => !r)}
                   hitSlop={10}
                   style={{ minHeight: TAP, justifyContent: 'center', alignItems: 'center' }}>
          <Text style={[T.caption, { color: P.brand }]}>
            {showRetired ? 'Hide retired gear' : 'Show retired gear'}
          </Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

function FilterChip({ label, on, onPress }: {
  label: string; on: boolean; onPress: () => void;
}) {
  const { P } = useTheme();
  return (
    <Pressable onPress={onPress} hitSlop={8} style={{
      minHeight: 38, justifyContent: 'center', paddingHorizontal: S[4],
      borderRadius: RA.pill, borderWidth: 1,
      borderColor: on ? P.brand : P.hairlineStrong,
      backgroundColor: on ? P.brand : P.card,
    }}>
      <Text style={[T.caption, { color: on ? P.onBrand : P.textPri }]}>{label}</Text>
    </Pressable>
  );
}

function GearRow({ item, onPress }: { item: GearItem; onPress: () => void }) {
  const { P } = useTheme();
  const retired = item.status !== 'active';
  const subtitle = [item.brand, item.model, item.size && `Size ${item.size}`]
    .filter(Boolean).join(' · ');
  return (
    <Card onPress={onPress} style={{ opacity: retired ? 0.6 : 1 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: S[3] }}>
        <View style={{ flex: 1, gap: S[1] }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: S[2] }}>
            {item.favorite && <Star color={P.warning} filled size={15} />}
            <Text style={[T.title, { color: P.textPri, flexShrink: 1 }]} numberOfLines={1}>
              {item.name}
            </Text>
          </View>
          {!!subtitle && <Muted>{subtitle}</Muted>}
          <View style={{ flexDirection: 'row', gap: S[2], marginTop: S[1],
                         alignItems: 'center', flexWrap: 'wrap' }}>
            {!!item.category_key && <Pill label={titleCase(item.category_key)} />}
            {item.weight_g !== null && <Muted>{weight(item.weight_g)}</Muted>}
            {retired && <Pill label={item.status} tone={P.textMuted} />}
          </View>
        </View>
        <Chevron color={P.textMuted} />
      </View>
    </Card>
  );
}
