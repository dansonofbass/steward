/** The dot between two parts of a line ("Undo · 12 left"). The dot is hidden from a screen reader and the spaces
 *  around it are not, so the parts never run together into one word ("$108,000about 11 years earlier", gate finding
 *  THO-10). Every hidden separator goes through here; `spokenMatchesShown.test.ts` fails on a hand-rolled one. */
export function Sep({ className }: { className?: string }) {
  return <>{' '}<span className={className} aria-hidden="true">·</span>{' '}</>;
}
