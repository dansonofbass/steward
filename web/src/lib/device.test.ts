import { describe, expect, it } from 'vitest';
import { deviceLabel, deviceName } from './device';

describe('deviceName', () => {
  it.each([
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1', 'iPhone'],
    ['Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15', 'iPad'],
    ['Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile', 'Android phone'],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120', 'Windows PC'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15', 'Mac'],
    ['Mozilla/5.0 (X11; Linux x86_64) Firefox/120', 'This device'],
    ['', 'This device'],
  ])('%s -> %s', (ua, expected) => {
    expect(deviceName(ua)).toBe(expected);
  });
});

describe('deviceLabel', () => {
  it.each([
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1', 'iPhone · Safari'],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36 Edg/120', 'Windows PC · Edge'],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36', 'Windows PC · Chrome'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17 Safari/605.1.15', 'Mac · Safari'],
    ['Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0', 'Firefox'],
    ['Mozilla/5.0 (X11; Linux x86_64)', 'Browser'],
    ['', 'Browser'],
  ])('%s -> %s', (ua, expected) => {
    expect(deviceLabel(ua)).toBe(expected);
  });
  it('never returns the current-device marker', () => {
    expect(deviceLabel('')).not.toBe('This device');
  });
});
