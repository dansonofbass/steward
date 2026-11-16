// "Ask about this" (phase 13 spec, P1): a quiet pill with the Ask tab's icon and the word Ask, named "Ask about
// {thing}", shown only when chat is on in the book. Eager and tiny: it imports nothing from screens/chat
// (src/ask/imports.test.ts); clicking opens the lazy panel, and hovering or focusing it loads that chunk early.
import { MessageCircleQuestionMark } from 'lucide-react';
import type { AboutIn, Surface } from '../ask/about';
import { preloadAsk } from '../ask/panel';
import { openAsk } from '../ask/store';
import { useBook } from '../book/BookContext';
import { ASK, ASK_ABOUT } from '../lib/copy';
import { Button } from './Button';

type Props = { about: AboutIn; surface: Surface; thing: string; className?: string };

export function AskAbout({ about, surface, thing, className }: Props) {
  const chat = useBook()?.chat === true;
  if (!chat) return null;
  return (
    <Button variant="quiet" icon={MessageCircleQuestionMark} className={className ? `ask-about ${className}` : 'ask-about'}
      aria-label={ASK_ABOUT.replace('{thing}', thing)} onPointerEnter={preloadAsk} onFocus={preloadAsk}
      onClick={(e) => { openAsk(about, surface, e.currentTarget); }}>
      {ASK}
    </Button>
  );
}
