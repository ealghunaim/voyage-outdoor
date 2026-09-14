import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Text, View } from 'react-native';

import {
  ActivitySchema, AdventureDetail as AdventureT, AdventureStatus, WeatherDay,
  deleteAdventure, getActivitySchema, getAdventure, refreshWeather,
  updateAdventure,
} from '../api';
import { dropCache, useCached } from '../cache';
import { describeAttributes } from '../components/AttributeFields';
import {
  Banner, Btn, Card, H, Label, Loading, Muted, Pill, Row, Screen,
} from '../components/ui';
import { day, titleCase } from '../format';
import { S, T, tint, useTheme } from '../theme';

/** What this status may become, mirroring api/adventures/router.py.
 *  The SERVER decides — this exists so the screen stops offering what it knows
 *  will be refused, and it must stay a strict subset of TRANSITIONS there. A
 *  409 is still handled; the point is to make it rare, not to pretend it
 *  cannot happen. */
const NEXT: Record<AdventureStatus, AdventureStatus[]> = {
  draft: ['planned'],
  planned: ['active', 'completed'],
  active: ['completed'],
  completed: [],
  archived: ['planned'],
};

const VERB: Record<AdventureStatus, string> = {
  draft: 'Back to draft',
  planned: 'Mark as planned',
  active: 'Start it',
  completed: 'Mark as done',
  archived: 'Archive',
};

export default function AdventureDetail({ adventureId, onEdit, onPack,
                                          onImportKit, onGone }: {
  adventureId: string;
  onEdit: () => void;
  onPack: (title: string) => void;
  onImportKit: (title: string) => void;
  onGone: () => void;
}) {
  const { P } = useTheme();
  const a = useCached<AdventureT>(`adventure.${adventureId}`,
    () => getAdventure(adventureId));
  // The adventure's own activity. A fishing trip's fields are trip type, days,
  // technique and target species; asking the trail-running schema about them
  // returns an empty spec list, which looks like a trip nobody filled in.
  const adv0 = a.data;
  const schema = useCached<ActivitySchema>(
    adv0?.activity_key ? `schema.${adv0.activity_key}` : null,
    () => getActivitySchema(adv0!.activity_key));

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wx, setWx] = useState<WeatherDay[] | null>(null);
  const [wxNote, setWxNote] = useState<string | null>(null);

  const adv = a.data;

  // Fetched once when the screen opens, and only when there is a location to
  // fetch for. The GET deliberately does not reach a weather provider — a read
  // that depends on a third party is a read that fails when they do, and this
  // screen has to render at a trailhead on one bar.
  useEffect(() => {
    if (!adv || adv.lat === null || adv.lng === null) return;
    let alive = true;
    refreshWeather(adventureId)
      .then(r => {
        if (!alive) return;
        if (r.days) setWx(r.days);
        if (r.reason === 'beyond_horizon' || r.reason === 'unavailable') {
          setWxNote(r.detail ?? null);
        }
      })
      .catch(() => { /* the stored forecast, if any, is already on screen */ });
    return () => { alive = false; };
  }, [adventureId, adv?.lat, adv?.lng, adv]);

  const days = wx ?? adv?.weather ?? [];

  //: Attributes that have a card of their own and must not also appear as a
  //: row in the specs list. `describeAttributes` joins a string_list with
  //: commas, which for a twenty-one line mandatory kit produced one paragraph
  //: reading "Running Pack - To carry mandatory kit throughout the race,
  //: Smartphone - LiveTrail application must be installed…" squeezed into the
  //: right-hand column of a label/value row, with the label itself wrapping
  //: mid-word to make room. It is the correct renderer for terrain; it is the
  //: wrong one for a checklist.
  const OWN_CARD = ['mandatory_kit'];

  const specs = useMemo(() => {
    if (!adv || !schema.data) return [];
    const fields = Object.fromEntries(
      Object.entries(schema.data.adventure).filter(([k]) => !OWN_CARD.includes(k)));
    return describeAttributes(fields, adv.attributes ?? {});
  }, [adv, schema.data]);

  const setStatus = async (status: AdventureStatus) => {
    setBusy(true);
    setError(null);
    try {
      await updateAdventure(adventureId, { status });
      await Promise.all([dropCache('adventures.live'), dropCache('adventures.all')]);
      await a.refresh();
    } catch (e: any) {
      setError(e?.message ?? 'Could not update that.');
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = () => {
    Alert.alert(
      'Delete this adventure?',
      'Archiving keeps it and takes it out of your list. Deleting is permanent — but any runs you logged against it stay on the gear, because they still happened.',
      [{ text: 'Cancel', style: 'cancel' },
       { text: 'Archive instead', onPress: () => setStatus('archived') },
       { text: 'Delete', style: 'destructive', onPress: async () => {
           try {
             await deleteAdventure(adventureId);
             await Promise.all([dropCache('adventures.live'),
                                dropCache('adventures.all'),
                                dropCache(`adventure.${adventureId}`)]);
             onGone();
           } catch (e: any) { setError(e?.message ?? 'Could not delete that.'); }
         } }],
    );
  };

  if (a.loading) return <Loading label="Loading…" />;
  if (!adv) {
    return (
      <Screen>
        <Banner tone="error" text={a.error ?? 'That adventure is not available offline.'} />
        <Btn kind="quiet" label="Back" onPress={onGone} />
      </Screen>
    );
  }

  const oneDay = adv.start_date.slice(0, 10) === adv.end_date.slice(0, 10);
  // Read straight off the attributes rather than from a derived spec row: this
  // is a list, and describeAttributes renders it as one joined string.
  const kit: string[] = (adv.attributes?.mandatory_kit as string[]) ?? [];
  const fishing = adv.activity_key === 'fishing';

  return (
    <Screen>
      {a.stale && <Banner text="Saved copy — reconnecting." />}
      {!!error && <Banner tone="error" text={error} />}

      <View style={{ gap: S[2] }}>
        <H>{adv.title}</H>
        <View style={{ flexDirection: 'row', gap: S[2], flexWrap: 'wrap' }}>
          <Pill label={adv.status}
                tone={adv.status === 'active' ? P.success : P.brand}
                filled={adv.status === 'active'} />
          <Pill label={titleCase(adv.activity_key)} />
        </View>
        <Text style={[T.body, { color: P.textSec }]}>
          {oneDay ? day(adv.start_date) : `${day(adv.start_date)} – ${day(adv.end_date)}`}
          {adv.place_name ? ` · ${adv.place_name}` : ''}
        </Text>
      </View>

      {specs.length > 0 && (
        <Card style={{ gap: S[1] }}>
          <Label>{fishing ? "The trip" : "The run"}</Label>
          {specs.map(s => <Row key={s.label} label={s.label} value={s.value} />)}
        </Card>
      )}

      <Card style={{ gap: S[3] }}>
        <Label>Weather</Label>
        {adv.lat === null ? (
          <Muted>Add a place to this adventure to get its forecast.</Muted>
        ) : days.length === 0 ? (
          <Muted>{wxNote ?? 'No forecast stored yet.'}</Muted>
        ) : (
          <View style={{ gap: S[2] }}>
            {days.map(d => <WeatherRow key={d.id ?? d.forecast_date} d={d} />)}
            <Muted>
              {days[0].provider === 'met-no'
                ? 'MET Norway — no rain probability in this source.'
                : 'Open-Meteo'}
            </Muted>
          </View>
        )}
        {!!wxNote && days.length > 0 && <Muted>{wxNote}</Muted>}
      </Card>

      {/* Kept ABOVE the pack card on purpose: mandatory kit outranks every
          rule the pack engine runs, so the order on screen is the order of
          authority. Importing after building a pack rebuilds it anyway. */}
      <Card style={{ gap: S[3] }}>
        <Label>Mandatory kit</Label>
        {kit.length === 0 ? (
          <Muted>
            {fishing
              // §24 says display authoritative rules "where available". For an
              // expedition to somewhere uninhabited there is no organiser and
              // no published list, so saying "import it from the race page"
              // would be offering a door that does not exist.
              ? 'Nothing recorded. There is no organiser publishing a list for '
                + 'this kind of trip — anything you add here is treated as '
                + 'non-negotiable and marked critical on the pack.'
              : "Nothing recorded. If this is a race with a kit list, read it in "
                + "from the race's own page — those items outrank every other "
                + 'rule, and the pack marks each one critical.'}
          </Muted>
        ) : (
          <View style={{ gap: S[1] }}>
            {kit.slice(0, 6).map((line, i) => (
              <Text key={i} style={[T.body, { color: P.textSec }]}>· {line}</Text>
            ))}
            {kit.length > 6 && <Muted>+{kit.length - 6} more</Muted>}
          </View>
        )}
        {/* The import path is a race-page reader. Offering it on a trip with
            no organiser is offering a door to nowhere, so fishing gets the
            honest alternative: type it. */}
        {fishing ? (
          <Muted>Add required items by editing this adventure.</Muted>
        ) : (
          <Btn kind="ghost"
               label={kit.length ? 'Re-read the race page' : 'Import from the race page'}
               onPress={() => onImportKit(adv.title)} />
        )}
      </Card>

      <Card style={{ gap: S[3] }}>
        <Label>Smart pack</Label>
        <Muted>
          Rule-based code over this adventure, your locker and the forecast
          above. Every line says which rule put it there, and no model decides
          any of it.
        </Muted>
        <Btn kind="ghost" label="Open the pack" onPress={() => onPack(adv.title)} />
      </Card>

      <View style={{ gap: S[3], paddingTop: S[2] }}>
        {NEXT[adv.status].map(next => (
          <Btn key={next} kind={next === 'planned' ? 'primary' : 'ghost'}
               label={VERB[next]} busy={busy} onPress={() => setStatus(next)} />
        ))}
        <Btn kind="quiet" label="Edit" onPress={onEdit} />
        {adv.status !== 'archived' && (
          <Btn kind="quiet" label="Archive" onPress={() => setStatus('archived')} />
        )}
        <Btn kind="quiet" label="Delete" tone={P.danger} onPress={confirmDelete} />
      </View>
    </Screen>
  );
}

function WeatherRow({ d }: { d: WeatherDay }) {
  const { P } = useTheme();
  const temp = d.temp_min !== null && d.temp_max !== null
    ? `${Math.round(d.temp_min)}–${Math.round(d.temp_max)}°`
    : '—';
  // NULL rain is rendered as an em dash, never as 0%. MET Norway carries no
  // precipitation probability at all, and printing "0%" would state that rain
  // is impossible on the strength of a provider having no opinion.
  const rain = d.precip_prob === null ? '—' : `${Math.round(d.precip_prob)}%`;
  const wind = d.wind_kph === null ? '—' : `${Math.round(d.wind_kph)} kph`;
  const cold = d.temp_min !== null && d.temp_min <= 5;
  const wet = d.precip_prob !== null && d.precip_prob >= 60;

  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: S[3],
                   paddingVertical: S[1],
                   backgroundColor: wet || cold ? tint(P.warning, 0.08) : undefined,
                   borderRadius: 8, paddingHorizontal: wet || cold ? S[2] : 0 }}>
      <Text style={[T.caption, { color: P.textMuted, width: 62 }]}>
        {d.forecast_date.slice(5)}
      </Text>
      <Text style={[T.body, { color: P.textPri, width: 78 }]}>{temp}</Text>
      <Text style={[T.caption, { color: wet ? P.warningInk : P.textSec, width: 54 }]}>
        {rain}
      </Text>
      <Text style={[T.caption, { color: P.textSec, flex: 1, textAlign: 'right' }]}>
        {wind}
      </Text>
    </View>
  );
}
