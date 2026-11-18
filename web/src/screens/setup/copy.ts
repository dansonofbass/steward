// Release spec 2026-11-05, section 6: the first run's page. Lazy with its screen, so none of it is in the first load.
export const HEADING = 'Set up Steward';
export const LEDE = 'Make the first account. You can invite others later.';
export const YOUR_NAME = 'Your name';
export const PASSWORD_HINT = 'At least 12 characters.';
export const MAKE_ACCOUNT = 'Make my account';
// The command as docs/quickstart/install.md gives it; the page sets it as code wherever it appears (issue #20).
export const SETUP_COMMAND = 'docker compose run --rm steward steward setup';
export const NO_LINK = 'Open the link that docker compose run --rm steward steward setup printed.';
// The server's words (steward/auth/setup_link.py LINK_GONE), for a link this page finds gone before it asks.
// tests/test_setup_link.py keeps the two the same.
export const LINK_GONE = 'This link has expired or was already used. Run docker compose run --rm steward steward setup again for a new one.';
export const PASSKEY_HEADING = 'Add a passkey?';
export const PASSKEY_LEDE = 'Next time, sign in with this device instead of your password.';
export const ADD_PASSKEY = 'Add a passkey';
export const NOT_NOW = 'Not now';
export const DIDNT_FINISH = "That didn't finish. Try again.";
