import { cleanup, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { stubFetch, wrapBook } from '../../test-utils';
import { GatewayOffLine } from './GatewayOffLine';

afterEach(() => { vi.unstubAllGlobals(); setCurrentBook('ours'); });
const status = (away_long: boolean) => ({ on: true, gateway: { state: away_long ? 'away' : 'ok', line: '', last_answered: null, checked: null, checks: null, away_long } });

describe('The gateway off on Home', () => {
  it('shows after 10 minutes away to people with chat on', async () => {
    stubFetch({ '/api/chat': status(true) });
    wrapBook(<GatewayOffLine />, { chat: true });
    expect(await screen.findByText('The gateway is off, so chat and categorization are paused')).toBeInTheDocument();
  });

  it('shows the oops face in a household book, and none in a parent book', async () => {
    stubFetch({ '/api/chat': status(true) });
    wrapBook(<GatewayOffLine />, { chat: true });
    expect(await screen.findByTestId('gateway-off')).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('svg.acorn')).toHaveAttribute('data-face', 'oops'));
    cleanup();
    stubFetch({ '/api/chat': status(true) });
    wrapBook(<GatewayOffLine />, { chat: true, kind: 'parent' });
    expect(await screen.findByText('The gateway is off, so chat and categorization are paused')).toBeInTheDocument();
    expect(document.querySelector('svg.acorn')).toBeNull();
  });

  it('stays hidden before 10 minutes, and asks nothing where chat is off', async () => {
    stubFetch({ '/api/chat': status(false) });
    const { container } = wrapBook(<GatewayOffLine />, { chat: true });
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
    const fetchMock = stubFetch({ '/api/chat': status(true) });
    wrapBook(<GatewayOffLine />, { chat: false });
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
