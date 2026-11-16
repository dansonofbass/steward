import { Plus, Trash2 } from 'lucide-react';
import './Design.css';
import { NET_WORTH, NOTHING_HERE_YET, ADD_A_BANK_OR_ACCOUNT, SAVE, SEARCH, SEARCH_HINT, SIGN_OUT } from '../lib/copy';
import { Acorn } from '../ui/Acorn';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { EmptyState } from '../ui/EmptyState';
import { Field } from '../ui/Field';
import { IconLabel } from '../ui/IconLabel';
import { Money } from '../ui/Money';
import { NAV_ITEMS, Nav } from '../ui/Nav';
import { Notice } from '../ui/Notice';
import { Sheet } from '../ui/Sheet';
import { Skeleton } from '../ui/Skeleton';
import { Sparkline } from '../ui/Sparkline';

// 90 literal-ish demo points: a gentle climb with a wobble, in cents.
const DEMO_POINTS = Array.from({ length: 90 }, (_, i) => 118_400_000 + i * 70_000 + Math.round(Math.sin(i / 5) * 900_000));

const SIZES = ['s', 'm', 'l', 'xl'] as const;
const noop = () => {};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="design__section">
      <h3 className="design__h">{title}</h3>
      {children}
    </section>
  );
}

function Specimens() {
  return (
    <div className="design__stack">
      <Section title="Type scale">
        {[6, 5, 4, 3, 2, 1].map((n) => (
          <p key={n} className="num" style={{ fontSize: `var(--fs-${n})` }}>
            --fs-{n} · $1,234,567.89
          </p>
        ))}
      </Section>

      <Section title="Acorn">
        <div className="design__acorns">
          {(['win', 'golden', 'resting', 'oops'] as const).map((f) => <Acorn key={f} face={f} size={48} label={f} season={null} />)}
          <Acorn face="win" size={48} label="fall" season="fall" />
          <Acorn face="win" size={48} label="snow" season="snow" />
        </div>
      </Section>

      <Section title="Money">
        {SIZES.map((s) => (
          <div key={s} className="design__row">
            <Money cents={125_700_000} size={s} />
            <Money cents={-5_412} size={s} />
            <Money cents={0} size={s} />
          </div>
        ))}
        <div className="design__row">
          <Money cents={125_700_000} size="l" compact />
          <Money cents={5} size="l" sign="always" />
        </div>
      </Section>

      <Section title="Buttons">
        {(['primary', 'quiet', 'danger'] as const).map((v) => (
          <div key={v} className="design__row">
            <Button variant={v}>{v === 'danger' ? SIGN_OUT : SAVE}</Button>
            <Button variant={v} className="is-hover">Hover</Button>
            <Button variant={v} busy>Busy</Button>
            <Button variant={v} disabled>Disabled</Button>
          </div>
        ))}
        <div className="design__row">
          <Button icon={Plus}>With icon</Button>
          <Button variant="danger" icon={Trash2}>Remove</Button>
        </div>
      </Section>

      <Section title="Icon with label">
        <IconLabel icon={Plus} label="Always a visible label" />
      </Section>

      <Section title="Fields">
        <Field label={SEARCH} hint={SEARCH_HINT}>
          <input type="search" />
        </Field>
        <Field label="Amount" error="Enter a number, like 12.50.">
          <input type="text" defaultValue="twelve" />
        </Field>
      </Section>

      <Section title="Card">
        <Card>
          <p className="num" style={{ color: 'var(--ink-muted)' }}>{NET_WORTH}</p>
          <Money cents={125_700_000} size="xl" compact />
          <Sparkline points={DEMO_POINTS} />
        </Card>
      </Section>

      <Section title="Skeleton">
        <Skeleton lines={3} />
      </Section>

      <Section title="Empty state">
        <EmptyState title={NOTHING_HERE_YET} body={ADD_A_BANK_OR_ACCOUNT} action={<Button variant="quiet">Open Settings</Button>} />
      </Section>

      <Section title="Notices">
        <Notice tone="info">Your bank was updated a moment ago.</Notice>
        <Notice tone="warn">This bank has not updated in 9 days.</Notice>
        <Notice tone="error">Steward could not reach the bank.</Notice>
      </Section>

      <Section title="Navigation">
        <div className="design__frame design__frame--phone">
          <Nav items={NAV_ITEMS} count={3} layout="bar" />
        </div>
        <div className="design__frame design__frame--desktop">
          <Nav items={NAV_ITEMS} count={3} layout="rail" home={NAV_ITEMS[0].to} />
        </div>
      </Section>

      <Section title="Sheet">
        <Sheet open onClose={noop} title="Pick a category" inline>
          <p>Sheets rise from the bottom on phones and slide in from the right on wide screens.</p>
        </Sheet>
      </Section>
    </div>
  );
}

export default function Design() {
  return (
    <div className="design">
      <h1 className="design__title">Design</h1>
      <div className="design__cols">
        <div className="theme-light design__col" data-theme="light">
          <h2 className="design__theme">Light</h2>
          <Specimens />
        </div>
        <div className="theme-dark design__col" data-theme="dark">
          <h2 className="design__theme">Dark</h2>
          <Specimens />
        </div>
      </div>
    </div>
  );
}
