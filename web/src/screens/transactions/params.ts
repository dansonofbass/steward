/** Merge one param into a query string, keeping everything else. An empty value removes the key. */
export function withParam(search: string, key: string, value: string): URLSearchParams {
  const next = new URLSearchParams(search);
  if (value === '') next.delete(key);
  else next.set(key, value);
  return next;
}
