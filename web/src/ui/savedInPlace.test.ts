// 16i review I-2: a form in a sheet that saves without closing tells the sheet, so a close after a good save asks
// nothing. A scan of every sheet with a text box, and of the forms shown inside sheets from other files: each calls
// useSheetSaved(), or is listed here with why it needn't (it closes on save, or its box empties).
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

const TEXT_BOX = /<input\b|<textarea\b|<MoneyInput\b|<Affix\b|<Field\b/;
/** Forms that show inside a sheet but are written in another file. */
const SHEET_CONTENT = [
  '/src/screens/transactions/TxnDetail.tsx', '/src/screens/transactions/NoteForm.tsx', '/src/screens/ready/EmailPanel.tsx',
  '/src/screens/ready/BackupsPanel.tsx', '/src/screens/ready/PairForm.tsx', '/src/screens/spending/setasides/SetAsideForm.tsx',
];

/** Sheets and sheet forms that needn't tell the sheet, with why. */
const NEEDNT: Record<string, string> = {
  '/src/screens/accounts/ManualAccounts.tsx': 'Update and Add account close on save',
  '/src/screens/plan/NextDollar.tsx': "the settings sheet closes on save; the rate and payroll boxes are on the page",
  '/src/ui/CategoryMenu.tsx': 'a search box, which holds no draft',
  '/src/screens/care/QuoteSheet.tsx': 'closes on save',
  '/src/screens/settings/InviteSheet.tsx': 'closes on save, or swaps in the pass, whose box is read-only',
  '/src/screens/accounts/invest/PositionsImport.tsx': 'hands the result to the account page, which closes it',
  '/src/screens/import/Look.tsx': 'Done closes it; nothing is saved before',
  '/src/screens/Transactions.tsx': "its sheet's forms are TxnDetail's and NoteForm's, which tell it",
  '/src/screens/settings/Members.tsx': 'Reset password closes on save',
  '/src/screens/sameaccount/MergeInto.tsx': 'radio buttons only; the merge closes it',
  '/src/screens/Design.tsx': 'the design page shows a sample; it saves nothing',
  '/src/screens/care/ScenarioSheet.tsx': 'closes on save',
  '/src/screens/reimburse/TripSheet.tsx': 'hands the trip to its page, which closes it',
  '/src/screens/settings/AddBookSheet.tsx': 'opens the new book, or hands it back, which closes it',
  '/src/screens/inventory/Suggestions.tsx': 'radio buttons only; linking closes it',
  '/src/screens/watching/MarkSheet.tsx': 'closes on save',
  '/src/screens/transactions/Filters.tsx': 'filters apply as they change; nothing waits to be saved',
  '/src/screens/you/SignInDevices.tsx': 'Add this device closes on success',
  '/src/screens/chat/ChatSettings.tsx': 'Turn on closes on success',
  '/src/screens/reimburse/SettleSheet.tsx': 'closes on settle',
  '/src/screens/ready/PairForm.tsx': 'empties its code box on success, so nothing differs from the start',
  '/src/screens/spending/setasides/SetAsideForm.tsx': 'the edit sheet closes on save',
};

function sheetForms(sources: Record<string, string>): string[] {
  return Object.entries(sources)
    .filter(([path, src]) => path !== '/src/ui/Sheet.tsx' && path !== '/src/ui/ConfirmSheet.tsx'
      && ((/<Sheet\b/.test(src) && TEXT_BOX.test(src)) || SHEET_CONTENT.includes(path)))
    .map(([path]) => path);
}

/** How a source uses the hook: each `const name = useSheetSaved(scope)` it holds. */
const uses = (src: string) => [...src.matchAll(/const (\w+) = useSheetSaved\(([^)]*)\)/g)].map((m) => ({ name: m[1], scope: m[2].trim() }));
const callsHook = (src: string) => /\buseSheetSaved\(/.test(src);

function problems(sources: Record<string, string>): string[] {
  const out: string[] = [];
  for (const path of sheetForms(sources)) {
    if (!callsHook(sources[path]) && !(path in NEEDNT)) out.push(`${path}: a sheet form that neither tells its sheet it saved (useSheetSaved) nor is listed`);
  }
  // Wherever the hook is used, in a sheet form or not: scoped to its form (re-review R-1), and its function called.
  for (const [path, src] of Object.entries(sources)) {
    if (path === '/src/ui/Sheet.tsx' || !callsHook(src)) continue;
    const found = uses(src);
    if (found.length === 0) out.push(`${path}: useSheetSaved() not kept as \`const name = useSheetSaved(formRef)\``);
    for (const { name, scope } of found) {
      if (!scope) out.push(`${path}: useSheetSaved() with no form to scope it, so a save would count another form's text as saved`);
      if (!new RegExp(`\\b${name}\\(\\)`).test(src.replace(`const ${name} = useSheetSaved(`, ''))) out.push(`${path}: ${name}, from useSheetSaved, is never called after a save`);
    }
  }
  return out;
}

describe('forms that save in place tell their sheet (16i review I-2)', () => {
  it('every sheet form calls useSheetSaved or says why it needn\'t', () => {
    expect(sheetForms(SOURCES).length).toBeGreaterThanOrEqual(25);
    expect(problems(SOURCES)).toEqual([]);
  });

  it('the forms that save and stay open call it', () => {
    for (const path of ['/src/screens/transactions/TxnDetail.tsx', '/src/screens/transactions/NoteForm.tsx', '/src/screens/ready/EmailPanel.tsx', '/src/screens/ready/BackupsPanel.tsx']) {
      expect(SOURCES[path], path).toMatch(/useSheetSaved\(formRef\)/);
      expect(SOURCES[path], path).toMatch(/<form ref=\{formRef\}/);
    }
  });

  it('the list never goes stale: each entry exists, is a sheet form, and doesn\'t call it', () => {
    const forms = new Set(sheetForms(SOURCES));
    for (const path of Object.keys(NEEDNT)) {
      expect(forms.has(path), path).toBe(true);
      expect(SOURCES[path], path).not.toMatch(/\buseSheetSaved\(/);
    }
  });

  it('catches a new sheet form that says nothing, one not scoped to its form, and one that never calls the function', () => {
    expect(problems({ '/src/x.tsx': '<Sheet open><input value={v} /></Sheet>' })).toHaveLength(1);
    expect(problems({ '/src/x.tsx': 'const saved = useSheetSaved(formRef);\nsaved();\n<Sheet open><form ref={formRef}><input /></form></Sheet>' })).toEqual([]);
    expect(problems({ '/src/x.tsx': 'const saved = useSheetSaved();\nsaved();\n<Sheet open><input /></Sheet>' }))
      .toEqual(["/src/x.tsx: useSheetSaved() with no form to scope it, so a save would count another form's text as saved"]);
    expect(problems({ '/src/x.tsx': 'const saved = useSheetSaved(formRef);\n<Sheet open><form ref={formRef}><input /></form></Sheet>' }))
      .toEqual(['/src/x.tsx: saved, from useSheetSaved, is never called after a save']);
  });
});
