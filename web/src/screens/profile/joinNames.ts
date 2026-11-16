/** "Ava", "Ava and Ben", "Ava, Ben and Cy" (a done row's summary). */
export const joinNames = (names: string[]): string =>
  names.length <= 1 ? names[0] ?? '' : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
