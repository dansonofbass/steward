// Spec 3.3: Home says the gateway is off only to people with chat on in this book, and only after 10 minutes without an
// answer, so a reboot doesn't flash it (plan B ruling 29).
import { useBook } from '../../book/BookContext';
import { GATEWAY_OFF_HOME } from '../../lib/copy';
import { gw } from '../../lib/gatewayName';
import { Notice } from '../../ui/Notice';
import { LazyOopsAcorn } from '../../ui/LazyOopsAcorn';
import { useChatStatus } from '../chat/api';

export function GatewayOffLine() {
  const book = useBook();
  const on = book?.chat === true && book.available;
  const s = useChatStatus(on);
  if (!on || !s.data?.gateway.away_long) return null;
  return <Notice tone="warn"><span className="gateway-off" data-testid="gateway-off"><LazyOopsAcorn />{gw(GATEWAY_OFF_HOME)}</span></Notice>;
}
