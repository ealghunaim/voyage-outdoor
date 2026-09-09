import React, { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { RaceKitDraft, acceptKitDraft, createKitDraft, discardKitDraft } from '../api';
import { dropCache } from '../cache';
import {
  Banner, Btn, Card, Field, H, Label, Muted, Pill, Screen,
} from '../components/ui';
import { S, T, TAP, useTheme } from '../theme';

/**
 * Import a race's mandatory equipment list (§24).
 *
 * THE SCREEN IS THE SAFEGUARD. Mandatory kit outranks every rule in the pack
 * engine and every line it produces is marked critical, so this is the one
 * place in the app where a model's output becomes a fact — and it only does so
 * after a person has looked at it against the source and ticked it.
 *
 * Which is why nothing here is pre-confirmed and nothing is hidden: every
 * extracted line is shown, editable, with the condition the page attached to
 * it, next to where it was read from. A kit list you did not read is a kit list
 * you cannot rely on at a check, and a screen that made accepting easier than
 * reading would produce exactly that.
 */
export default function RaceKitImport({ adventureId, adventureTitle, onDone, onCancel }: {
  adventureId: string;
  adventureTitle: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { P } = useTheme();
  const [url, setUrl] = useState('');
  const [paste, setPaste] = useState('');
  const [draft, setDraft] = useState<RaceKitDraft | null>(null);

  //: Keyed by index rather than by text: two identical lines on a race page are
  //: two items, and de-duplicating them here would silently drop one.
  const [lines, setLines] = useState<string[]>([]);
  const [taken, setTaken] = useState<boolean[]>([]);
  const [editing, setEditing] = useState<number | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const read = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = url.trim()
        ? { url: url.trim(), adventure_id: adventureId }
        : { text: paste, adventure_id: adventureId };
      const row = await createKitDraft(body);
      setDraft(row);
      const items = row.extracted?.items ?? [];
      setLines(items.map(i => i.text));
      // EVERYTHING STARTS TICKED, deliberately — and this is the one decision
      // on the screen worth arguing with. Starting unticked would make the
      // safe-looking default (accept nothing) the one that produces an
      // incomplete kit list, and an incomplete mandatory list is the failure
      // that ends a race. Untick what the page did not actually require.
      setTaken(items.map(() => true));
    } catch (e: any) {
      setError(e?.message ?? 'Could not read that.');
    } finally {
      setBusy(false);
    }
  };

  const accept = async () => {
    if (!draft) return;
    const chosen = lines.filter((_, i) => taken[i]).map(s => s.trim()).filter(Boolean);
    if (!chosen.length) {
      setError('Nothing is ticked, so there is nothing to add.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await acceptKitDraft(draft.id, adventureId, chosen);
      // The pack was rebuilt server-side against the new kit, and the cached
      // copies of both are now describing a race that has changed under them.
      await Promise.all([dropCache(`pack.${adventureId}`),
                         dropCache(`narrative.${adventureId}`),
                         dropCache(`adventure.${adventureId}`)]);
      onDone();
    } catch (e: any) {
      setError(e?.message ?? 'Could not save that.');
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    if (draft) { try { await discardKitDraft(draft.id); } catch { /* nothing owed */ } }
    onCancel();
  };

  // ── step 1: where to read from ────────────────────────────────────────────
  if (!draft) {
    return (
      <Screen>
        <H>Race kit</H>
        <Muted>
          Read the mandatory equipment list off the race's own page, for
          {' '}{adventureTitle}. Nothing is added until you have checked it.
        </Muted>

        {!!error && <Banner tone="error" text={error} />}

        <Card style={{ gap: S[4] }}>
          <Field label="Race page address" value={url} onChange={setUrl}
                 placeholder="https://…" keyboardType="url" />
          <Muted>
            Some race sites build their pages in the browser and come back empty
            here. If that happens, paste the list instead — it is usually faster.
          </Muted>
        </Card>

        <Card style={{ gap: S[4] }}>
          <Field label="…or paste the equipment section" value={paste}
                 onChange={setPaste} multiline
                 placeholder="Copy the mandatory equipment part of the page and paste it here." />
        </Card>

        <View style={{ gap: S[3], paddingTop: S[2] }}>
          <Btn label="Read it" onPress={read} busy={busy}
               disabled={!url.trim() && !paste.trim()} />
          {/* Measured: a real kit page takes ~25 seconds. A spinner that long
              with nothing beside it reads as hung, and the second tap costs
              another read. */}
          {busy && (
            <Muted>
              Reading the whole page and pulling out the equipment. This takes
              about half a minute — it is not stuck.
            </Muted>
          )}
          <Btn kind="quiet" label="Cancel" onPress={onCancel} />
        </View>
      </Screen>
    );
  }

  // ── step 2: check it, then accept ─────────────────────────────────────────
  const extracted = draft.extracted ?? { items: [], recommended: [], note: null } as any;
  const chosenCount = taken.filter(Boolean).length;

  return (
    <Screen>
      <H>Check this list</H>

      <Card style={{ gap: S[1] }}>
        <Label>
          {[draft.race_name, draft.edition, draft.event].filter(Boolean).join(' · ')
           || 'Read from the page'}
        </Label>
        <Muted>
          {draft.source_kind === 'url'
            ? draft.source_url
            : 'From the text you pasted'}
        </Muted>
      </Card>

      {!!error && <Banner tone="error" text={error} />}

      {/* The model's own account of how it read the page. Shown, not buried:
          "this page listed three distances and I took the 100km one" is
          precisely the thing that makes a kit list wrong in a way that looks
          right. */}
      {!!extracted.note && <Banner text={extracted.note} />}

      {lines.length === 0 ? (
        <Card style={{ gap: S[3] }}>
          <Label>No equipment list found</Label>
          <Text style={[T.body, { color: P.textSec }]}>
            Nothing on that page read as a mandatory equipment list. That is the
            honest answer rather than a guess — an invented kit list is the one
            thing worse than none, because you would pack from it.
          </Text>
          <Btn kind="quiet" label="Try another page" onPress={() => setDraft(null)} />
        </Card>
      ) : (
        <Card style={{ gap: S[3] }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between',
                         alignItems: 'center' }}>
            <Label>Mandatory</Label>
            <Muted>{chosenCount} of {lines.length}</Muted>
          </View>
          <Muted>
            Tap to untick anything the race does not actually require. Tap the
            wording to fix it.
          </Muted>

          {lines.map((line, i) => (
            <View key={i} style={{ gap: S[2] }}>
              {editing === i ? (
                <Field label={`Item ${i + 1}`} value={line}
                       onChange={t => setLines(prev =>
                         prev.map((v, j) => (j === i ? t : v)))}
                       multiline />
              ) : (
                <Pressable
                  onPress={() => setTaken(prev =>
                    prev.map((v, j) => (j === i ? !v : v)))}
                  onLongPress={() => setEditing(i)}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: taken[i] }}
                  accessibilityLabel={line}
                  style={{ minHeight: TAP, flexDirection: 'row',
                           alignItems: 'center', gap: S[3] }}>
                  <View style={{
                    width: 24, height: 24, borderRadius: 7, borderWidth: 2,
                    borderColor: taken[i] ? P.brand : P.hairlineStrong,
                    backgroundColor: taken[i] ? P.brand : 'transparent',
                    alignItems: 'center', justifyContent: 'center',
                  }}>
                    {taken[i] && (
                      <Text style={{ color: P.onBrand, fontSize: 14,
                                     fontWeight: '700' }}>✓</Text>
                    )}
                  </View>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={[T.body, {
                      color: taken[i] ? P.textPri : P.textMuted,
                    }]}>
                      {line}
                    </Text>
                    {/* The page's own qualifier, kept attached to its item.
                        "Only for the 100km" is the difference between a kit
                        check and two kilos of kit you did not need. */}
                    {!!extracted.items?.[i]?.condition && (
                      <Muted>{extracted.items[i].condition}</Muted>
                    )}
                    {/* And the page's reasoning, here rather than in the item's
                        name. This is the screen where "the LiveTrail app must
                        be installed, airplane mode is forbidden" is worth
                        reading; the pack list is not. */}
                    {!!extracted.items?.[i]?.detail && (
                      <Text style={[T.caption, { color: P.textSec }]}>
                        {extracted.items[i].detail}
                      </Text>
                    )}
                  </View>
                </Pressable>
              )}
              {editing === i && (
                <Btn kind="quiet" label="Done" onPress={() => setEditing(null)} />
              )}
            </View>
          ))}
        </Card>
      )}

      {!!extracted.recommended?.length && (
        <Card style={{ gap: S[2] }}>
          <Label>Recommended by the race, not required</Label>
          <Muted>
            These are not added. They are not mandatory, and the pack list treats
            mandatory as non-negotiable — putting a suggestion in there would
            make the list mean less.
          </Muted>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: S[2],
                         paddingTop: S[1] }}>
            {extracted.recommended.map((r: string) => <Pill key={r} label={r} />)}
          </View>
        </Card>
      )}

      {lines.length > 0 && (
        <View style={{ gap: S[3], paddingTop: S[2] }}>
          <Btn label={`Add ${chosenCount} to ${adventureTitle}`} onPress={accept}
               busy={busy} disabled={!chosenCount} />
          <Muted>
            This replaces the mandatory kit on this adventure and rebuilds the
            pack. What you have already packed stays packed.
          </Muted>
          <Btn kind="quiet" label="Discard" onPress={discard} />
        </View>
      )}
    </Screen>
  );
}
