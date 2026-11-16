/** Where focus goes when the panel closes (P27): the button that opened it, or the page's h1 when that button is
 *  gone (a Review card that moved on). The h1 is made focusable if it isn't. */
export function focusBack(opener: HTMLElement | null): HTMLElement | null {
  if (opener?.isConnected) return opener;
  const h = document.querySelector<HTMLElement>('main h1') ?? document.querySelector<HTMLElement>('h1');
  if (h && !h.hasAttribute('tabindex')) h.setAttribute('tabindex', '-1');
  return h;
}
