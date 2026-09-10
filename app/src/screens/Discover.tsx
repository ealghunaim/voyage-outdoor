import React from 'react';
import { Pressable, Text, View } from 'react-native';

import { Discover as DiscoverT, DiscoverFinding, getDiscover } from '../api';
import { useCached } from '../cache';
import {
  Banner, Card, H, Label, Loading, Muted, Pill, Screen,
} from '../components/ui';
import { RA, S, T, TAP, tint, useTheme } from '../theme';

/**
 * Discover (§14) — this runner's own record, read across every adventure.
 *
 * WHAT THIS SCREEN IS NOT. It is not a feed, and there is no product database
 * behind it. §0.4 says V1 has no live product data — admin-entered records
 * only — and puts scraping, an affiliate API and shopping data providers in a
 * research spike that has not been run and that nobody has decided on. So this
 * screen does not fetch from the internet, and it is built to be genuinely
 * useful at tens of catalog rows rather than to look thin until thousands
 * arrive.
 *
 * §14 asks for personalisation from activities, locker, adventures, brands and
 * equipment age, and explicitly not "a generic outdoor-news feed". The signal
 * turns out to already be in the database: a gap is invisible one pack at a
 * time, and obvious the moment you count it across four.
 *
 * SETTLED IS THE SECTION THAT MATTERS. §14 makes the willingness to recommend
 * NOT buying the trust anchor and calls it non-negotiable. A discovery screen
 * that only lists what is absent is a shop whatever its buttons say, so what
 * you do not need is given the same weight as what you lack.
 */
const SECTIONS: {
  kind: DiscoverFinding['kind']; title: string; blurb: string;
}[] = [
  { kind: 'gap', title: 'Gaps',
    blurb: 'Counted across every adventure, not one list at a time.' },
  { kind: 'attention', title: 'Worth a look',
    blurb: 'What the gear-health rules flagged. A prompt, never a deadline.' },
  { kind: 'settled', title: 'Settled',
    blurb: 'Things you do not need. This is as much the point as the rest.' },
];

export default function Discover() {
  const { P } = useTheme();
  const d = useCached<DiscoverT>('discover', getDiscover);

  if (d.loading) return <Loading label="Reading your record…" />;

  const findings = d.data?.findings ?? [];
  const snap = d.data?.snapshot ?? {};

  return (
    <Screen>
      <View style={{ paddingTop: S[4], gap: S[2] }}>
        <H>Discover</H>
        <Muted>
          Everything here comes from your own gear and adventures. Nothing is
          fetched from the internet and nothing is for sale.
        </Muted>
      </View>

      {d.stale && <Banner text="Saved copy — reconnecting." />}
      {!!d.error && !d.data && <Banner tone="error" text={d.error} />}

      {findings.length === 0 && (
        <Card style={{ gap: S[3] }}>
          <Label>Nothing to report</Label>
          <Text style={[T.body, { color: P.textSec }]}>
            {snap.packs
              ? 'Your packs are complete and no gear is flagged. That is the '
                + 'good version of an empty screen.'
              : 'Build a pack for an adventure and this fills in — gaps, gear '
                + 'worth checking, and what you can stop thinking about.'}
          </Text>
        </Card>
      )}

      {SECTIONS.map(section => {
        const rows = findings.filter(f => f.kind === section.kind);
        if (!rows.length) return null;
        return (
          <Card key={section.kind} style={{ gap: S[4] }}>
            <View style={{ gap: S[1] }}>
              <View style={{ flexDirection: 'row', alignItems: 'center',
                             justifyContent: 'space-between' }}>
                <Label>{section.title}</Label>
                <Muted>{rows.length}</Muted>
              </View>
              <Muted>{section.blurb}</Muted>
            </View>
            {rows.map((f, i) => <FindingRow key={`${f.title}-${i}`} f={f} />)}
          </Card>
        );
      })}

      {findings.length > 0 && (
        <Muted>
          {d.data?.ruleset} · {snap.adventures ?? 0} adventure(s) ·
          {' '}{snap.packs ?? 0} pack(s) · {snap.catalog_size ?? 0} catalog item(s)
        </Muted>
      )}
    </Screen>
  );
}

function FindingRow({ f }: { f: DiscoverFinding }) {
  const { P } = useTheme();
  const accent = f.kind === 'settled' ? P.success
    : f.critical ? P.critical
    : f.required ? P.warningInk : P.textMuted;

  return (
    <View style={{ flexDirection: 'row', gap: S[3], minHeight: TAP }}>
      <View style={{ width: 3, borderRadius: 2, backgroundColor: accent }} />
      <View style={{ flex: 1, gap: S[1] }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: S[2],
                       flexWrap: 'wrap' }}>
          <Text style={[T.title, { color: P.textPri }]}>{f.title}</Text>
          {f.critical && (
            <View style={{ paddingHorizontal: S[2], paddingVertical: 1,
                           borderRadius: RA.pill,
                           backgroundColor: tint(P.critical, 0.16) }}>
              <Text style={[T.label, { color: P.critical }]}>CRITICAL</Text>
            </View>
          )}
          {f.mandatory && <Pill label="Race kit" />}
          {/* Said explicitly rather than left to the absence of a CRITICAL
              badge. "Optional" is the information, not the lack of a warning. */}
          {f.kind === 'gap' && !f.required && <Pill label="Optional" />}
        </View>

        <Text style={[T.body, { color: P.textSec }]}>{f.detail}</Text>

        {/* Curated products, and ONLY under a required gap. Specs, no price and
            no link: products.specs is objective fact (§28), and the moment a
            price appears the screen is answering a different question from the
            one that was asked. */}
        {f.catalog.length > 0 && (
          <View style={{ gap: S[1], paddingTop: S[1] }}>
            <Muted>In the catalog, in this category:</Muted>
            {f.catalog.map(c => (
              <Text key={c.id} style={[T.caption, { color: P.textSec }]}>
                · {[c.brand, c.model, c.generation].filter(Boolean).join(' ')}
                {Object.keys(c.specs).length
                  ? `  — ${Object.entries(c.specs).slice(0, 3)
                        .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v}`).join(', ')}`
                  : ''}
              </Text>
            ))}
          </View>
        )}
      </View>
    </View>
  );
}
