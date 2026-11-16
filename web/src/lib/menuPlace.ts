/** Where the desktop category menu goes (sorting redesign, The picker): about 320 x 380 under the trigger, or above it
 *  when there is more room there, never nearer than 16 px to the viewport's edge and never under 160 px tall. Page
 *  coordinates (the scroll added), so the menu scrolls with the page and needs no scroll listener (Performance 4). */
export const MENU_W = 320; // two columns of rows, wrapping, with no sideways scroll (CategoryMenu.css)
export const MENU_H = 380;
export const MENU_GUTTER = 16;
const GAP = 4;
const MIN_H = 160;

export type MenuPlace = { left: number; top: number; width: number; height: number; above: boolean };

export function menuPlace(r: { left: number; top: number; bottom: number }, vw: number, vh: number,
  scrollX: number, scrollY: number): MenuPlace {
  const below = vh - r.bottom - GAP - MENU_GUTTER;
  const overhead = r.top - GAP - MENU_GUTTER;
  const above = below < MENU_H && overhead > below;
  const height = Math.max(MIN_H, Math.min(MENU_H, above ? overhead : below));
  const width = Math.min(MENU_W, vw - MENU_GUTTER * 2);
  const left = Math.min(Math.max(r.left, MENU_GUTTER), vw - MENU_GUTTER - width);
  const top = above ? r.top - GAP - height : r.bottom + GAP;
  return { left: Math.round(left + scrollX), top: Math.round(top + scrollY), width, height: Math.round(height), above };
}
