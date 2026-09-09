import React, { useEffect, useMemo, useState } from 'react';
import { View } from 'react-native';

import {
  ActivitySchema, GearCategory, createGear, getActivitySchema,
  getGear, listCategories, updateGear,
} from '../api';
import { AttributeFields, AttrValues } from '../components/AttributeFields';
import { Banner, Btn, Card, Chip, Field, H, Label, Loading, Muted, Screen, Toggle } from '../components/ui';
import { dropCache } from '../cache';
import { S } from '../theme';

const ACTIVITY = 'trail_running';   // the only built activity in V1

/**
 * Add or edit one piece of gear.
 *
 * MANUAL ENTRY IS THE PRIMARY PATH (§6, §0.4). There is no product search in
 * V1, so this form is how the locker gets filled, and it is built to be fast:
 * name is the only thing required, everything else is optional, and the
 * activity-specific fields appear only once a category is chosen.
 */
export default function GearForm({ gearId, onDone, onCancel }: {
  gearId?: string;
  onDone: (id: string) => void;
  onCancel: () => void;
}) {
  const editing = !!gearId;

  const [loading, setLoading] = useState(editing);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [schema, setSchema] = useState<ActivitySchema | null>(null);
  const [categories, setCategories] = useState<GearCategory[]>([]);

  const [name, setName] = useState('');
  const [brand, setBrand] = useState('');
  const [model, setModel] = useState('');
  const [categoryKey, setCategoryKey] = useState<string | null>(null);
  const [size, setSize] = useState('');
  const [weightG, setWeightG] = useState('');
  const [notes, setNotes] = useState('');
  const [favorite, setFavorite] = useState(false);
  const [attributes, setAttributes] = useState<AttrValues>({});

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [s, c] = await Promise.all([
          getActivitySchema(ACTIVITY),
          listCategories(ACTIVITY),
        ]);
        if (!alive) return;
        setSchema(s);
        setCategories(c);
        if (gearId) {
          const item = await getGear(gearId);
          if (!alive) return;
          setName(item.name);
          setBrand(item.brand ?? '');
          setModel(item.model ?? '');
          setCategoryKey(item.category_key);
          setSize(item.size ?? '');
          setWeightG(item.weight_g === null ? '' : String(item.weight_g));
          setNotes(item.notes ?? '');
          setFavorite(item.favorite);
          setAttributes(item.attributes ?? {});
        }
      } catch (e: any) {
        if (alive) setError(e?.message ?? 'Could not load the form.');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [gearId]);

  // The fields for the chosen category, straight from the server's registry.
  // Nothing in this file knows what a trail shoe has.
  const fields = useMemo(
    () => (categoryKey && schema ? schema.gear[categoryKey] ?? {} : {}),
    [schema, categoryKey],
  );

  const changeCategory = (key: string) => {
    const next = categoryKey === key ? null : key;
    setCategoryKey(next);
    // Attributes belong to a category. Keeping a stack height after the item
    // becomes a headlamp would leave a value that no form can show and no
    // engine should read — and the server would drop it as an unknown key
    // anyway, so the screen would disagree with the record.
    const keep = next && schema ? schema.gear[next] ?? {} : {};
    setAttributes(prev => Object.fromEntries(
      Object.entries(prev).filter(([k]) => k in keep)));
  };

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const parsedWeight = weightG.trim() === '' ? null : parseInt(weightG, 10);
      const body = {
        name: name.trim(),
        brand: brand.trim() || null,
        model: model.trim() || null,
        category_key: categoryKey,
        activity_key: ACTIVITY,
        size: size.trim() || null,
        weight_g: Number.isFinite(parsedWeight as number) ? parsedWeight : null,
        notes: notes.trim() || null,
        favorite,
        attributes,
      };
      const saved = editing
        ? await updateGear(gearId!, body)
        : await createGear(body);
      // The list's cache entries are now wrong in a way this screen cannot
      // patch — a new item changes counts and ordering. Dropping them is one
      // line; reconciling them would be a cache library.
      await Promise.all([dropCache('gear.active'), dropCache('gear.all'),
                         dropCache(`gear.${saved.id}`)]);
      onDone(saved.id);
    } catch (e: any) {
      // A 422 from the attribute validator names its field, so it is shown as
      // written rather than replaced with something generic.
      setError(e?.message ?? 'Could not save.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Loading label="Loading…" />;

  return (
    <Screen>
      <H>{editing ? 'Edit gear' : 'Add gear'}</H>

      {!!error && <Banner tone="error" text={error} />}

      <Card style={{ gap: S[4] }}>
        <Field label="Name" value={name} onChange={setName}
               placeholder="Norda 005" />
        <View style={{ flexDirection: 'row', gap: S[3] }}>
          <View style={{ flex: 1 }}>
            <Field label="Brand" value={brand} onChange={setBrand} placeholder="Norda" />
          </View>
          <View style={{ flex: 1 }}>
            <Field label="Model" value={model} onChange={setModel} placeholder="005" />
          </View>
        </View>
      </Card>

      <Card style={{ gap: S[3] }}>
        <Label>Category</Label>
        <Muted>Choosing one adds the fields that category actually has.</Muted>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: S[2] }}>
          {categories.map(c => (
            <Chip key={c.key} label={c.name} selected={categoryKey === c.key}
                  onPress={() => changeCategory(c.key)} />
          ))}
        </View>
      </Card>

      <Card style={{ gap: S[4] }}>
        <View style={{ flexDirection: 'row', gap: S[3] }}>
          <View style={{ flex: 1 }}>
            <Field label="Size" value={size} onChange={setSize} placeholder="EU 45" />
          </View>
          <View style={{ flex: 1 }}>
            <Field label="Weight" unit="g" value={weightG}
                   onChange={t => setWeightG(t.replace(/[^0-9]/g, ''))}
                   keyboardType="numeric" placeholder="—" />
          </View>
        </View>
        <Toggle label="Favourite" value={favorite} onChange={setFavorite} />
      </Card>

      {Object.keys(fields).length > 0 && (
        <Card style={{ gap: S[4] }}>
          <View style={{ gap: S[1] }}>
            <Label>{categories.find(c => c.key === categoryKey)?.name ?? 'Details'}</Label>
            <Muted>
              These fields come from the activity schema on the server, not from
              this screen.
            </Muted>
          </View>
          <AttributeFields fields={fields} values={attributes} onChange={setAttributes} />
        </Card>
      )}

      <Card>
        <Field label="Notes" value={notes} onChange={setNotes} multiline
               placeholder="Anything you want to remember about this one." />
      </Card>

      <View style={{ gap: S[3], paddingTop: S[2] }}>
        <Btn label={editing ? 'Save changes' : 'Add to locker'} onPress={save}
             busy={saving} disabled={!name.trim()} />
        <Btn kind="quiet" label="Cancel" onPress={onCancel} />
      </View>
    </Screen>
  );
}
