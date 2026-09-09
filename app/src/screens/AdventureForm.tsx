import React, { useEffect, useMemo, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import {
  ActivitySchema, Place, createAdventure, getActivitySchema, getAdventure,
  searchPlaces, updateAdventure,
} from '../api';
import { dropCache } from '../cache';
import { AttributeFields, AttrValues } from '../components/AttributeFields';
import {
  Banner, Btn, Card, Field, H, Label, Loading, Muted, Screen,
} from '../components/ui';
import { RA, S, T, TAP, useTheme } from '../theme';

const ACTIVITY = 'trail_running';

/** YYYY-MM-DD, the only date format this app stores or shows in a field.
 *  An adventure happens on calendar days, so there is no time and no timezone
 *  arithmetic anywhere in this screen. */
const ISO = /^\d{4}-\d{2}-\d{2}$/;

export default function AdventureForm({ adventureId, onDone, onCancel }: {
  adventureId?: string;
  onDone: (id: string) => void;
  onCancel: () => void;
}) {
  const { P } = useTheme();
  const editing = !!adventureId;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [schema, setSchema] = useState<ActivitySchema | null>(null);

  const [title, setTitle] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [place, setPlace] = useState<Place | null>(null);
  const [placeName, setPlaceName] = useState('');
  const [attributes, setAttributes] = useState<AttrValues>({});

  // Place search: typed query, candidate list, and whether a lookup is running.
  const [query, setQuery] = useState('');
  const [candidates, setCandidates] = useState<Place[] | null>(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const s = await getActivitySchema(ACTIVITY);
        if (!alive) return;
        setSchema(s);
        if (adventureId) {
          const a = await getAdventure(adventureId);
          if (!alive) return;
          setTitle(a.title);
          setStartDate(a.start_date.slice(0, 10));
          setEndDate(a.end_date.slice(0, 10));
          setPlaceName(a.place_name ?? '');
          setAttributes(a.attributes ?? {});
          if (a.lat !== null && a.lng !== null) {
            setPlace({ name: a.place_name ?? '', admin: null, country: null,
                       country_code: a.country_code, lat: a.lat, lng: a.lng,
                       elevation_m: null });
          }
        }
      } catch (e: any) {
        if (alive) setError(e?.message ?? 'Could not load the form.');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [adventureId]);

  const fields = useMemo(() => schema?.adventure ?? {}, [schema]);

  const runSearch = async () => {
    if (query.trim().length < 2) return;
    setSearching(true);
    setError(null);
    try {
      const found = await searchPlaces(query.trim());
      setCandidates(found);
      if (found.length === 0) setError(`Nothing found for "${query.trim()}".`);
    } catch (e: any) {
      setError(e?.message ?? 'Place lookup failed.');
    } finally {
      setSearching(false);
    }
  };

  const choose = (p: Place) => {
    setPlace(p);
    setPlaceName([p.name, p.admin, p.country].filter(Boolean).join(', '));
    setCandidates(null);
    setQuery('');
  };

  const dateProblem = (() => {
    if (!ISO.test(startDate)) return 'Start date must look like 2027-02-05.';
    if (endDate && !ISO.test(endDate)) return 'End date must look like 2027-02-06.';
    if (endDate && endDate < startDate) return 'The end date is before the start.';
    return null;
  })();

  const save = async () => {
    setError(null);
    if (dateProblem) { setError(dateProblem); return; }
    setSaving(true);
    try {
      const body: any = {
        title: title.trim(),
        place_name: placeName.trim() || null,
        country_code: place?.country_code ?? null,
        lat: place?.lat ?? null,
        lng: place?.lng ?? null,
        start_date: startDate,
        // A one-day race is the common case; the server defaults end to start
        // when this is absent, so an unfilled field is not an error.
        end_date: endDate || startDate,
        attributes,
      };
      if (!editing) body.activity_key = ACTIVITY;
      const saved = editing
        ? await updateAdventure(adventureId!, body)
        : await createAdventure(body);
      await Promise.all([dropCache('adventures.live'), dropCache('adventures.all'),
                         dropCache(`adventure.${saved.id}`)]);
      onDone(saved.id);
    } catch (e: any) {
      // A 422 from the attribute validator names its field — shown as written.
      setError(e?.message ?? 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Loading label="Loading…" />;

  return (
    <Screen>
      <H>{editing ? 'Edit adventure' : 'Plan an adventure'}</H>

      {!!error && <Banner tone="error" text={error} />}

      <Card style={{ gap: S[4] }}>
        <Field label="Name" value={title} onChange={setTitle}
               placeholder="Oman by UTMB — 100M" />
        <View style={{ flexDirection: 'row', gap: S[3] }}>
          <View style={{ flex: 1 }}>
            <Field label="Start" value={startDate} onChange={setStartDate}
                   placeholder="2027-02-05" />
          </View>
          <View style={{ flex: 1 }}>
            <Field label="End" value={endDate} onChange={setEndDate}
                   placeholder="same day" />
          </View>
        </View>
        {!!dateProblem && <Muted>{dateProblem}</Muted>}
      </Card>

      <Card style={{ gap: S[3] }}>
        <Label>Where</Label>
        {place ? (
          <View style={{ gap: S[2] }}>
            <Text style={[T.body, { color: P.textPri }]}>{placeName}</Text>
            <Muted>
              {place.lat.toFixed(3)}, {place.lng.toFixed(3)}
              {place.elevation_m !== null ? ` · ${place.elevation_m} m` : ''}
            </Muted>
            <Btn kind="quiet" label="Change" onPress={() => { setPlace(null); setPlaceName(''); }} />
          </View>
        ) : (
          <View style={{ gap: S[3] }}>
            <Muted>
              Coordinates are what the forecast is fetched for, so this is a
              lookup rather than a free-text field.
            </Muted>
            <Field label="Search" value={query} onChange={setQuery}
                   placeholder="Bidiyah, Chamonix, Snowdonia…" />
            <Btn kind="ghost" label="Find" onPress={runSearch} busy={searching}
                 disabled={query.trim().length < 2} />

            {/* A LIST, never a best guess. "Chamonix" is unambiguous;
                "Springfield" is fourteen places on four continents, and
                choosing silently would put the forecast on the wrong
                continent with nothing on screen looking wrong. */}
            {candidates?.map((c, i) => (
              <Pressable key={`${c.lat},${c.lng},${i}`} onPress={() => choose(c)}
                         style={{ minHeight: TAP, justifyContent: 'center',
                                  paddingHorizontal: S[4], borderRadius: RA.md,
                                  borderWidth: 1, borderColor: P.hairline,
                                  backgroundColor: P.sunken }}>
                <Text style={[T.body, { color: P.textPri }]}>
                  {[c.name, c.admin, c.country].filter(Boolean).join(', ')}
                </Text>
                <Muted>
                  {c.lat.toFixed(2)}, {c.lng.toFixed(2)}
                  {c.elevation_m !== null ? ` · ${c.elevation_m} m` : ''}
                </Muted>
              </Pressable>
            ))}
          </View>
        )}
      </Card>

      {Object.keys(fields).length > 0 && (
        <Card style={{ gap: S[4] }}>
          <View style={{ gap: S[1] }}>
            <Label>The run</Label>
            <Muted>
              These fields come from the trail running schema on the server, not
              from this screen.
            </Muted>
          </View>
          <AttributeFields fields={fields} values={attributes} onChange={setAttributes} />
        </Card>
      )}

      <View style={{ gap: S[3], paddingTop: S[2] }}>
        <Btn label={editing ? 'Save changes' : 'Create adventure'} onPress={save}
             busy={saving} disabled={!title.trim() || !startDate} />
        <Btn kind="quiet" label="Cancel" onPress={onCancel} />
      </View>
    </Screen>
  );
}
