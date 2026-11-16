import { ChevronDown, X } from 'lucide-react';
import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import type { Account } from '../../api/types';
import { CATEGORY_ORDER, label } from '../../lib/categories';
import { radioFocusKeys, radioTab } from '../../lib/radioKeys';
import {
  ALL_TIME, BUSINESS, CUSTOM, DATES, DATE_FROM, DATE_TO, FILTER_ACCOUNT, FILTER_BUSINESS, FILTER_CATEGORY, FILTER_PERSON,
  FILTER_SORTED, LAST_30, LAST_7, PERSONAL, SORTED_STEWARD, SORTED_UNSURE, THIS_MONTH,
} from '../../lib/copy';
import { Field } from '../../ui/Field';
import { useBook } from '../../book/BookContext';
import { ownerOptions } from '../settings/shared';
import { Sheet } from '../../ui/Sheet';
import { DATES_MODES, type DatesMode } from './dates';

export type FilterKey = 'dates' | 'account' | 'category' | 'owner' | 'business' | 'sorted';
export type FilterValues = { account_id?: number; category?: string; owner?: string; business?: boolean; sorted?: string };

const MODE_LABEL: Record<DatesMode, string> = { '7': LAST_7, '30': LAST_30, month: THIS_MONTH, all: ALL_TIME, custom: CUSTOM };

type Props = {
  open: FilterKey | null;
  onOpen: (k: FilterKey | null) => void;
  mode: DatesMode;
  from: string;
  to: string;
  onMode: (m: DatesMode) => void;
  onCustom: (from: string, to: string) => void;
  values: FilterValues;
  accounts: Account[];
  /** One account's page: the account is set by the page, so there is no Account chip. */
  fixedAccount?: boolean;
  onChange: (changes: Record<string, string | null>) => void;
  /** Shown last in the row of filters (bulk sort's Select). */
  extra?: ReactNode;
};

type Option = { value: string; label: string };

export function Filters({ open, onOpen, mode, from, to, onMode, onCustom, values, accounts, fixedAccount = false, onChange, extra }: Props) {
  const PEOPLE: Option[] = ownerOptions(useBook()?.owners);
  const accountOptions: Option[] = accounts.map((a) => ({ value: String(a.id), label: a.name }));
  const categoryOptions: Option[] = CATEGORY_ORDER.map((k) => ({ value: k, label: label(k) }));
  const businessOptions: Option[] = [{ value: 'true', label: BUSINESS }, { value: 'false', label: PERSONAL }];
  const sortedOptions: Option[] = [{ value: 'steward', label: SORTED_STEWARD }, { value: 'unsure', label: SORTED_UNSURE }];
  const find = (opts: Option[], v: string | number | boolean | undefined) => (v === undefined ? undefined : opts.find((o) => o.value === String(v))?.label);

  const chips: { key: FilterKey; name: string; param?: string; value?: string }[] = [
    ...(fixedAccount ? [] : [{ key: 'account' as const, name: FILTER_ACCOUNT, param: 'account_id', value: find(accountOptions, values.account_id) }]),
    { key: 'category', name: FILTER_CATEGORY, param: 'category', value: find(categoryOptions, values.category) },
    { key: 'owner', name: FILTER_PERSON, param: 'owner', value: find(PEOPLE, values.owner) },
    { key: 'business', name: FILTER_BUSINESS, param: 'business', value: find(businessOptions, values.business) },
    { key: 'sorted', name: FILTER_SORTED, param: 'sorted', value: find(sortedOptions, values.sorted) },
  ];

  const datesOn = mode !== 'all';
  const sheets: Record<Exclude<FilterKey, 'dates'>, { options: Option[]; current: string | undefined; param: string }> = {
    account: { options: accountOptions, current: values.account_id === undefined ? undefined : String(values.account_id), param: 'account_id' },
    category: { options: categoryOptions, current: values.category, param: 'category' },
    owner: { options: PEOPLE, current: values.owner, param: 'owner' },
    business: { options: businessOptions, current: values.business === undefined ? undefined : String(values.business), param: 'business' },
    sorted: { options: sortedOptions, current: values.sorted, param: 'sorted' },
  };
  const titles: Record<FilterKey, string> = { dates: DATES, account: FILTER_ACCOUNT, category: FILTER_CATEGORY, owner: FILTER_PERSON, business: FILTER_BUSINESS, sorted: FILTER_SORTED };

  return (
    <>
      <div className="filters" role="group" aria-label="Filters">
        <button type="button" className={`filter${datesOn ? ' is-on' : ''}`} aria-haspopup="dialog" onClick={() => onOpen('dates')}>
          {datesOn ? `${DATES}: ${MODE_LABEL[mode]}` : DATES}
          <ChevronDown size={20} aria-hidden="true" />
        </button>
        {chips.map((c) =>
          c.value ? (
            <button key={c.key} type="button" className="filter is-on" aria-label={`${c.name}: ${c.value}, clear`} onClick={() => onChange({ [c.param!]: null })}>
              {c.name}: {c.value}
              <X size={20} aria-hidden="true" />
            </button>
          ) : (
            <button key={c.key} type="button" className="filter" aria-haspopup="dialog" onClick={() => onOpen(c.key)}>
              {c.name}
              <ChevronDown size={20} aria-hidden="true" />
            </button>
          ),
        )}
        {extra}
      </div>

      <Sheet open={open === 'dates'} onClose={() => onOpen(null)} title={titles.dates}>
        {/* Arrows move focus only: choosing a range closes the sheet, so Enter or Space chooses. */}
        <div className="card lines" role="radiogroup" aria-label={DATES} onKeyDown={radioFocusKeys}>
          {DATES_MODES.filter((m) => m !== 'custom').map((m) => (
            <div className="line" key={m}>
              <button type="button" role="radio" aria-checked={mode === m} tabIndex={radioTab(mode === m)} className="txn-radio-row" onClick={() => { onMode(m); onOpen(null); }}>
                <span className="radio" aria-hidden="true" />
                <span>{MODE_LABEL[m]}</span>
              </button>
            </div>
          ))}
          <div className="line date-custom">
            <button type="button" role="radio" aria-checked={mode === 'custom'} tabIndex={radioTab(mode === 'custom')} className="txn-radio-row" onClick={() => onMode('custom')}>
              <span className="radio" aria-hidden="true" />
              <span>{CUSTOM}</span>
            </button>
            {mode === 'custom' && (
              <div className="grid-2">
                <Field label={DATE_FROM}><input type="date" value={from} max={to || undefined} onChange={(e) => onCustom(e.target.value, to)} /></Field>
                <Field label={DATE_TO}><input type="date" value={to} min={from || undefined} onChange={(e) => onCustom(from, e.target.value)} /></Field>
              </div>
            )}
          </div>
        </div>
      </Sheet>

      {open && open !== 'dates' && (
        <Sheet open onClose={() => onOpen(null)} title={titles[open]}>
          <Listbox
            name={titles[open]}
            options={sheets[open].options}
            current={sheets[open].current}
            onPick={(v) => { onChange({ [sheets[open].param]: v }); onOpen(null); }}
          />
        </Sheet>
      )}
    </>
  );
}

/** Arrow keys move focus between the radios; choosing is a click, Enter or Space. */
function Listbox({ name, options, current, onPick }: { name: string; options: Option[]; current: string | undefined; onPick: (v: string) => void }) {
  const list = useRef<HTMLUListElement>(null);
  function onKeyDown(e: KeyboardEvent<HTMLLIElement>, value: string) {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(value); return; }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const items = Array.from(list.current?.querySelectorAll<HTMLElement>('[role=option]') ?? []);
    const i = items.indexOf(e.currentTarget);
    items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
  }
  return (
    <ul ref={list} role="listbox" aria-label={name} className="card lines listbox">
      {options.map((o) => (
        <li key={o.value} role="option" aria-selected={current === o.value} tabIndex={0} className="line option" onClick={() => onPick(o.value)} onKeyDown={(e) => onKeyDown(e, o.value)}>
          {o.label}
        </li>
      ))}
    </ul>
  );
}
