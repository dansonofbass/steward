import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AboutIn, Surface } from '../ask/about';
import { AskPanel } from '../ask/panel';
import { askState, resetAsk } from '../ask/store';
import { wrapBook } from '../test-utils';
import { AskAbout } from './AskAbout';

afterEach(() => { resetAsk(); vi.restoreAllMocks(); });

const ABOUT: AboutIn = { kind: 'account', id: 12 };
const SURFACE: Surface = { kind: 'account', group: 'everyday' };
const button = (book = {}) => wrapBook(<AskAbout about={ABOUT} surface={SURFACE} thing="Checking" />, book);

describe('the Ask button (P1, decision 7)', () => {
  it('is there only when chat is on, for a viewer too', () => {
    const off = button();
    expect(screen.queryByRole('button')).toBeNull();
    off.unmount();
    button({ chat: true, role: 'viewer' });
    const b = screen.getByRole('button', { name: 'Ask about Checking' });
    expect(b).toHaveTextContent('Ask');
    expect(b).toHaveClass('ask-about', 'btn--quiet');
  });
  it('opens the panel with its about, its surface and itself as the opener', () => {
    button({ chat: true });
    const b = screen.getByRole('button', { name: 'Ask about Checking' });
    fireEvent.click(b);
    expect(askState()).toEqual({ mounted: true, open: true, about: ABOUT, surface: SURFACE, opener: b, seq: 1 });
  });
  it('hovering or focusing it loads the panel early', () => {
    const preload = vi.spyOn(AskPanel, 'preload').mockReturnValue(Promise.resolve({ default: () => null }) as never);
    button({ chat: true });
    const b = screen.getByRole('button', { name: 'Ask about Checking' });
    fireEvent.pointerEnter(b);
    fireEvent.focus(b);
    expect(preload).toHaveBeenCalledTimes(2);
  });
});
