import { afterEach, describe, expect, it, vi } from 'vitest';
import { setUnauthorizedHandler } from '../../api/client';
import { uploadFile } from './api';

class FakeXhr {
  static last: FakeXhr;
  status = 0;
  responseText = '';
  upload: { onprogress: ((e: unknown) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  constructor() { FakeXhr.last = this; }
  open() {}
  setRequestHeader() {}
  abort() {}
  send() {}
  finish(status: number, body: unknown) { this.status = status; this.responseText = JSON.stringify(body); this.onload?.(); }
}

afterEach(() => { vi.unstubAllGlobals(); setUnauthorizedHandler(null); });

describe('uploadFile', () => {
  it('calls the unauthorized handler on a 401, so an expired session goes to sign-in', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const p = uploadFile(new File(['x'], 'a.pdf'), {}, () => undefined);
    FakeXhr.last.finish(401, { error: 'Sign in first.' });
    await expect(p).rejects.toMatchObject({ status: 401, message: 'Sign in first.' });
    expect(handler).toHaveBeenCalledTimes(1);
  });
  it('does not call it for other refusals', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    const p = uploadFile(new File(['x'], 'a.pdf'), {}, () => undefined);
    FakeXhr.last.finish(413, { error: 'Too big.' });
    await expect(p).rejects.toMatchObject({ status: 413 });
    expect(handler).not.toHaveBeenCalled();
  });
});
