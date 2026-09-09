// Renders a form from the activity registry.
//
// THIS IS WHERE THE ATTRIBUTE MODEL PAYS FOR ITSELF. Nothing in this file knows
// what a trail shoe is. It reads FieldSpecs the server sent and draws the right
// control for each type, so adding "heel counter stiffness" to trail shoes — or
// the entire fly-rod category in Phase 7 — is a change to registry.py and a
// server restart, with no app release and no edit here.
//
// The counterpart on the server is api/activities/validate.py. These two must
// agree about what each type accepts; where they disagree, the server wins and
// the user sees a 422 naming the field. That is the right way round: a client
// that validates loosely is a nuisance, a server that validates loosely is a
// data-integrity problem.

import React from 'react';
import { View } from 'react-native';

import type { FieldSpec } from '../api';
import { S } from '../theme';
import { Chip, Field, Label, Muted, Toggle } from './ui';

export type AttrValues = Record<string, any>;

function unitFor(spec: FieldSpec): string | undefined {
  if (!spec.unit && spec.min === undefined && spec.max === undefined) return undefined;
  const range = spec.min !== undefined && spec.max !== undefined
    ? `${spec.min}–${spec.max}` : undefined;
  return [spec.unit, range].filter(Boolean).join(' · ') || undefined;
}

function One({ name, spec, value, onChange }: {
  name: string; spec: FieldSpec; value: any; onChange: (v: any) => void;
}) {
  switch (spec.type) {
    case 'bool':
      return <Toggle label={spec.label} value={value === true} onChange={onChange} />;

    case 'enum':
      return (
        <View style={{ gap: S[2] }}>
          <Label>{spec.label}</Label>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: S[2] }}>
            {(spec.options ?? []).map(opt => (
              <Chip
                key={opt}
                label={opt.replace(/_/g, ' ')}
                selected={value === opt}
                // Tapping the selected chip clears it. Without this an enum can
                // be set once and never un-set, because there is no other
                // affordance for "actually, I don't know".
                onPress={() => onChange(value === opt ? null : opt)}
              />
            ))}
          </View>
        </View>
      );

    case 'multi_enum': {
      const list: string[] = Array.isArray(value) ? value : [];
      return (
        <View style={{ gap: S[2] }}>
          <Label>{spec.label}</Label>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: S[2] }}>
            {(spec.options ?? []).map(opt => (
              <Chip
                key={opt}
                label={opt.replace(/_/g, ' ')}
                selected={list.includes(opt)}
                onPress={() => onChange(list.includes(opt)
                  ? list.filter(x => x !== opt)
                  : [...list, opt])}
              />
            ))}
          </View>
        </View>
      );
    }

    case 'string_list':
      return (
        <View style={{ gap: S[2] }}>
          <Field
            label={spec.label}
            // One per line rather than comma-separated: mandatory kit entries
            // are phrases ("Waterproof jacket, taped seams") and a comma inside
            // one would silently split it into two items the runner never
            // wrote.
            value={(Array.isArray(value) ? value : []).join('\n')}
            onChange={t => onChange(t.split('\n').map(s => s.trim()).filter(Boolean))}
            placeholder={'One per line'}
            multiline
          />
          <Muted>One per line</Muted>
        </View>
      );

    case 'int':
    case 'number':
      return (
        <Field
          label={spec.label}
          unit={unitFor(spec)}
          value={value === null || value === undefined ? '' : String(value)}
          onChange={t => {
            const cleaned = t.replace(spec.type === 'int' ? /[^0-9-]/g : /[^0-9.-]/g, '');
            if (cleaned === '' || cleaned === '-') { onChange(null); return; }
            const n = spec.type === 'int' ? parseInt(cleaned, 10) : parseFloat(cleaned);
            // NaN is sent as null rather than as NaN: JSON.stringify turns NaN
            // into `null` anyway, and doing it here means the value on screen
            // and the value in the request are the same thing.
            onChange(Number.isFinite(n) ? n : null);
          }}
          keyboardType={spec.type === 'int' ? 'numeric' : 'decimal-pad'}
          placeholder="—"
        />
      );

    case 'text':
      return (
        <Field label={spec.label} value={value ?? ''} onChange={onChange} multiline />
      );

    case 'string':
    default:
      return (
        <Field label={spec.label} unit={spec.unit} value={value ?? ''}
               onChange={onChange} placeholder="—" />
      );
  }
}

export function AttributeFields({ fields, values, onChange }: {
  fields: Record<string, FieldSpec>;
  values: AttrValues;
  onChange: (next: AttrValues) => void;
}) {
  const names = Object.keys(fields);
  if (!names.length) return null;
  return (
    <View style={{ gap: S[4] }}>
      {names.map(name => (
        <One
          key={name}
          name={name}
          spec={fields[name]}
          value={values[name]}
          onChange={v => {
            const next = { ...values };
            // null/'' remove the key rather than storing an empty value. The
            // server treats an explicit null as "clear this", and an empty
            // string would otherwise be stored as a real answer of "".
            if (v === null || v === undefined || v === '') delete next[name];
            else next[name] = v;
            onChange(next);
          }}
        />
      ))}
    </View>
  );
}

/** Attributes as a read-only spec list, for the detail screen. */
export function describeAttributes(fields: Record<string, FieldSpec>,
                                   values: AttrValues): { label: string; value: string }[] {
  return Object.entries(fields)
    .filter(([name]) => values?.[name] !== undefined && values?.[name] !== null)
    .map(([name, spec]) => {
      const raw = values[name];
      let text: string;
      if (spec.type === 'bool') text = raw ? 'Yes' : 'No';
      else if (Array.isArray(raw)) text = raw.map(v => String(v).replace(/_/g, ' ')).join(', ');
      else text = String(raw).replace(/_/g, ' ');
      return { label: spec.label, value: spec.unit ? `${text} ${spec.unit}` : text };
    });
}
