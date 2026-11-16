/** Which books' welcome this page load has already opened (guided setup spec 2.1). BookScope sends a person with an
 *  unmarked welcome to it from the book's Home, once per page load: leaving the welcome for Home must not bounce back
 *  while the mark is still being saved, and skipping the welcome marks it on the server, not here. */
const shown = new Set<string>();

export const welcomeShown = (slug: string): boolean => shown.has(slug);
export const noteWelcomeShown = (slug: string): void => { shown.add(slug); };
