import { describe, expect, it } from 'vitest';
import * as chat from '../screens/chat/copy';
import * as imp from '../screens/import/copy';
import * as lib from './copy';
import { POOLS } from './lines';

// Spec 2026-11-05, section 7: every line about the gateway names it through {gateway}, filled by gw().
const GATEWAY_COPY = [
  lib.BACKGROUND_WAITING, lib.GATEWAY_OFF_HOME, ...POOLS.gatewayBack,
  chat.NO_BUDGET, chat.AWAY_TITLE, chat.AWAY_LAST, chat.PAUSED_BOX, chat.LEGEND_MODEL, chat.CONFIRM_ONE, chat.CONFIRM_MANY,
  chat.POP_MODEL, chat.CHECKS_TITLE, chat.GATEWAY, chat.GATEWAY_OK, chat.GATEWAY_AWAY, chat.PDF_ON_GATEWAY,
  chat.GATEWAY_CHECKED, chat.CC_NOTE,
  imp.ST_READING_NEW, imp.ST_WAITING, imp.ST_NOT_PAIRED, imp.ST_OLD_GATEWAY, imp.ST_OLD_GATEWAY_PDF, imp.ST_READING_SCAN,
  imp.ST_OLD_HOLDINGS,
];

describe('gateway copy', () => {
  it('names the gateway only through {gateway}', () => {
    expect(GATEWAY_COPY.filter((t) => !t.includes('{gateway}'))).toEqual([]);
  });
});
