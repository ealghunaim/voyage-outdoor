import React, { useState } from 'react';
import { Text, View } from 'react-native';

import { AskAnswer, ask } from '../api';
import { Banner, Btn, Card, Field, H, Label, Muted, Screen } from '../components/ui';
import { S, T, useTheme } from '../theme';

/**
 * Ask Outdoor AI (§16) — grounded in this runner's own locker and adventures.
 *
 * NOT A CHAT. There is no thread, no history, no scrollback of turns. Three
 * reasons, in order of how much they matter:
 *
 *   1. Every answer is read against freshly-loaded data. A thread would answer
 *      the fourth question from a locker snapshot taken before the third, and
 *      the drift is invisible — the answer still sounds current.
 *   2. The expensive half of the prompt is the locker. Re-sending a growing
 *      transcript on every follow-up bills for the same gear list repeatedly.
 *   3. A thread is a place to accumulate a wrong premise. One question, one
 *      answer, against the record, is harder to talk into a corner.
 *
 * The cost of that is real: "what about in the rain?" has to be asked in full.
 * Suggested questions exist partly to make that cheap to do.
 */
const SUGGESTIONS = [
  'What am I missing for a long day in the mountains?',
  'Which of my shoes is closest to worn out?',
  'What should I check before my next adventure?',
];

export default function Ask({ adventureId, adventureTitle, onBack }: {
  adventureId?: string;
  adventureTitle?: string;
  onBack: () => void;
}) {
  const { P } = useTheme();
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [asked, setAsked] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    setAsked(q);
    // Cleared BEFORE the request, not after. A failed request that leaves the
    // previous answer on screen under a new question is the worst of both.
    setAnswer(null);
    try {
      setAnswer(await ask(q, adventureId));
    } catch (e: any) {
      setError(e?.message ?? 'Could not answer that.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <H>Ask</H>
      <Muted>
        {adventureTitle
          ? `Answered from your locker, your adventures, and the pack for ${adventureTitle}.`
          : 'Answered from your gear locker and your adventures — not from the internet.'}
      </Muted>

      <Card style={{ gap: S[4] }}>
        <Field label="Your question" value={question} onChange={setQuestion}
               multiline placeholder="Anything about your kit or your plans." />
        <Btn label="Ask" onPress={() => send(question)} busy={busy}
             disabled={!question.trim()} />
      </Card>

      {!!error && <Banner tone="error" text={error} />}

      {!!answer && (
        <Card style={{ gap: S[3] }}>
          <Label>{asked}</Label>
          <Text style={[T.body, { color: P.textPri, lineHeight: 22 }]}>
            {answer.answer}
          </Text>
          {/* What it could see, stated. An assistant that says "you have no
              waterproof" is making a claim about a locker — being able to check
              it read 23 items rather than 3 is the difference between a fact
              and a guess. */}
          <Muted>
            Read {answer.grounded_in.gear_items} item
            {answer.grounded_in.gear_items === 1 ? '' : 's'} in your locker and
            {' '}{answer.grounded_in.adventures} adventure
            {answer.grounded_in.adventures === 1 ? '' : 's'}
            {answer.grounded_in.pack ? ', plus this pack' : ''}.
          </Muted>
        </Card>
      )}

      {!answer && !busy && (
        <View style={{ gap: S[3] }}>
          <Label>Or try</Label>
          {SUGGESTIONS.map(s => (
            <Btn key={s} kind="quiet" label={s}
                 onPress={() => { setQuestion(s); send(s); }} />
          ))}
        </View>
      )}

      <Btn kind="quiet" label="Back" onPress={onBack} />
    </Screen>
  );
}
