// Schedule C lines a transaction can report on (business plan ruling 7). The server keeps the same list in
// steward/business/lines.py; the Business page gets its labels from the server.
export type BusinessLine = { key: string; number: string; label: string };

export const TXN_LINES: BusinessLine[] = [
  { key: 'income', number: '1', label: 'Income' },
  { key: 'advertising', number: '8', label: 'Advertising' },
  { key: 'car', number: '9', label: 'Car' },
  { key: 'contract_labor', number: '11', label: 'Contract labor' },
  { key: 'insurance', number: '15', label: 'Insurance' },
  { key: 'legal_professional', number: '17', label: 'Legal and professional' },
  { key: 'office', number: '18', label: 'Office' },
  { key: 'supplies', number: '22', label: 'Supplies' },
  { key: 'travel', number: '24a', label: 'Travel' },
  { key: 'meals', number: '24b', label: 'Meals' },
  { key: 'utilities', number: '25', label: 'Utilities' },
  { key: 'software', number: '27b', label: 'Software' },
  { key: 'other', number: '27b', label: 'Other' },
];

export function lineLabel(key: string): string {
  return TXN_LINES.find((l) => l.key === key)?.label ?? key;
}
