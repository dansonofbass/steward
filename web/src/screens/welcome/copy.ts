// The first run's words (guided setup spec 2.2 to 2.4), verbatim. The Link button reuses LINK from lib/copy.
export const HELLO_TITLE = 'Steward';
export const HELLO_LEDE = 'Secure, private, thoughtful. For you, and the people you look after.';
export const ZONE_LINE = 'Time zone: {zone}';
export const CHANGE = 'Change';
export const SET_UP = 'Set up my household';
export const LOOK_AROUND = 'Look around with a sample household first';
export const MAKING_SAMPLE = 'Making the sample…';
export const LATER = 'Later';
export const MONEY_TITLE = 'Bring in your money';
export const LINK_TITLE = 'Link your banks';
export const LINK_LINE = 'Balances and spending arrive each day through SimpleFIN Bridge, about $15 a year.';
export const IMPORT_TITLE = 'Import a file';
export const IMPORT_LINE = "CSV, OFX, QFX or a PDF statement from your bank's website.";
export const IMPORT = 'Import';
export const linkedLine = (n: number) => `Linked. ${n} ${n === 1 ? 'account' : 'accounts'}.`;
export const NEXT = 'Next';
export const SKIP_FOR_NOW = 'Skip for now';
export const SORT_TITLE = 'Sort a few';
export const sortWait = (n: number) => `${n} ${n === 1 ? 'waits' : 'wait'} in Review. Sort a few to get the feel.`;
export const START_SORTING = 'Start sorting';
export const NOTHING_TO_SORT = 'Nothing to sort.';
export const NOTHING_YET = 'Nothing to sort yet.';
// The extras and the planting (spec 2.5, 2.6).
export const EXTRAS_TITLE = 'A few extras';
export const EXTRAS_LEDE = 'All optional. Get Steward ready keeps them for later.';
export const PARTNER = 'Your partner'; export const PARTNER_LINE = 'See the books together.'; export const INVITE = 'Invite';
export const ASK = 'Ask'; export const ASK_LINE = 'Ask Claude about your money. Notes and account numbers stay here.';
export const EMAIL = 'Email'; export const EMAIL_LINE = 'For invites, password resets and alerts.';
export const BACKUPS = 'Backups'; export const backupsLine = (time: string) => `A copy each night at ${time}.`;
export const SET_UP_ROW = 'Set up'; export const CHECK = 'Check';
export const HELP_CARD_TITLE = 'Someone you help with money?';
export const HELP_CARD_LINE = 'A parent, or anyone whose bills you keep an eye on. They get a book of their own.';
export const ADD_THEIR_BOOK = 'Add their book';
export const inYourBooks = (book: string) => `${book} is in your books.`;
export const FINISH = 'Finish';
export const PLANTED = 'Planted.';
export const toGo = (n: number) => `Get Steward ready · ${n} to go`;
export const GO_HOME = 'Go to Home';
// The partner's welcome (spec 7.2 to 7.4), verbatim. {review} is the Review nav icon and the word Review.
export const welcomeTo = (book: string) => `Welcome to ${book}`;
export const keepsHousehold = (inviter: string | null) =>
  inviter ? `${inviter} keeps your household's money here, on your own server.` : 'Your household keeps its money here, on your own server.';
export const keepsParent = (inviter: string | null, book: string) =>
  `${inviter ?? 'Your household'} keeps ${book}'s money here, on your own server.`;
export const SEE_AND_CHANGE = 'You can see everything and change it.';
export const SEE_ONLY = 'You can see everything. Changes are for managers.';
export const SWITCHES = 'Your switches';
export const YOURS_ALONE = 'Yours alone.';
export const NAME_ON_WORK = 'Your name on your work';
export const MANAGER_WORK = 'Notes and sorts show who made them. Most changes can be undone for 15 minutes. New spending waits in {review} for a category.';
export const VIEWER_WORK = 'Every change shows who made it. Most can be undone for 15 minutes.';
export const SKIP = 'Skip';
