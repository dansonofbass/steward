// Letters are taken by code point (Array.from), so an emoji or other character outside the BMP is never split in half.
const first = (word: string, n = 1) => Array.from(word).slice(0, n).join('');

/** The letters in a person's circle (decision 4): the first letters of the first two words of their name ("JR Hale"
 *  is JH). A one-word name written in capitals is already initials and keeps two ("JR"); any other one-word name
 *  gives one letter ("alex" is A). With no name, the first two letters of the username. */
export function initials(display: string, username: string): string {
  const words = display.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return first(username, 2).toUpperCase();
  if (words.length === 1) {
    const [word] = words;
    return first(word, word === word.toUpperCase() ? 2 : 1).toUpperCase();
  }
  return (first(words[0]) + first(words[1])).toUpperCase();
}
