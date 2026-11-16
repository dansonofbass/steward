import type { RowKey, Status } from './api';

// The page heading is S_READY in lib/copy.ts.
export const NEED = (n: number) => (n === 1 ? '1 needs you' : `${n} need you`);
export const NOTHING_NEEDS = 'Nothing needs you.';
export const TITLES: Record<RowKey, string> = { household: 'Your household', money: 'Money coming in', ask: 'Ask', email: 'Email',
  backups: 'Backups', someone: 'Someone you help', address: 'Secure address', key: 'Encryption key' };
export const STATUS_WORD: Record<Status, string> = { done: 'Done', needs: 'Needs you', optional: 'Optional' };
export { COPY } from '../settings/inviteCopy';
export const COPY_SELECTED = "Couldn't copy, so the line is selected.";
export const ADD_LINE = "Add this line to Steward's settings file (.env), then restart Steward.";
export const ADD_GATEWAY_LINE = "Add this line to gateway.env in {gateway}'s config folder. Restart {gateway}, then Check again.";
export const RESTART = 'docker compose up -d';
export const CHECK_AGAIN = 'Check again';
export const NOT_YET = 'Not yet. Steward is still running with {value}. Restart it after saving the file.';
export const NOT_YET_UNSET = 'Not yet. Steward is still running without it. Restart it after saving the file.';
export const TOOK_EFFECT = 'Took effect.';
export const LINK_BANK = 'Link a bank'; export const IMPORT_FILE = 'Import a file';
export const SET_IN_FILE = 'Set in your settings file ({env})';
export const HOST = 'Host'; export const PORT = 'Port'; export const USER = 'User'; export const PASSWORD = 'Password'; export const FROM = 'From';
export const SET = 'Set'; export const NOT_SET = 'Not set';
export const SEND_TEST = 'Send a test'; export const REMOVE = 'Remove';
export const REMOVE_EMAIL = 'Remove the email settings?'; export const REMOVE_EMAIL_BODY = 'Invites and resets stop sending.';
export const REMOVE_EMAIL_LABEL = 'Remove the email settings'; export const EMAIL_REMOVED = 'Removed the email settings.';
export const REMOVE_PING = 'Remove the ping URL';
export const TIME = 'Time'; export const OFF = 'Off'; export const PING_URL = 'Ping URL';
export const COPIES_GO = 'Copies go to {dir}.';
export const CODE = 'Code'; export const PAIR = 'Pair'; export const PAIR_AGAIN = 'Pair again';
export const PAIR_AGAIN_Q = 'Pair again?'; export const PAIR_AGAIN_BODY = "Ask stops until it's done.";
export const TURN_ON = 'Turn on';
export const RUNS_ON = { cpu: 'Runs on the CPU.', cuda: 'Runs on an NVIDIA GPU.', rocm: 'Runs on an AMD GPU.' } as const;
export const FASTER_WITH_GPU = 'A GPU makes it faster';
export const GPU_GUIDE = 'https://github.com/steward-money/steward/blob/main/docs/guides/gpu.md';
// INS-22: the Secure address row, when this browser can't use passkeys at the address.
export const PASSKEY_UNTRUSTED = "This browser doesn't trust the certificate here, so passkeys won't work.";
export const PASSKEY_AT_IP = "Passkeys don't work at an IP address.";
export const TRUST_ROOT = "Trust Caddy's root certificate on each phone and computer.";
export const NAME_IT = 'Give this machine a name, and use it in STEWARD_BASE_URL.';
export const LAN_GUIDE_LINK = 'How';
export const LAN_GUIDE = 'https://github.com/steward-money/steward/blob/main/docs/guides/access.md#lan-only';
export const STEWARD_SETTINGS = "Steward's settings"; export const TIME_ZONE = 'Time zone'; export const GATEWAY_NAME = 'Gateway name';
export const PASSWORD_AGAIN = 'Enter the password again.';
