import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useMe } from '../api/hooks';
import { adoptPrefs, setPersonPrefs } from '../lib/celebrations';
import { setGatewayName } from '../lib/gatewayName';
import { setHouseholdZone } from '../lib/today';

/** Signed-in routes. Which book, the shell and Set up Steward are BookScope's job. The person's own switches (phase 17),
 *  the gateway's name and the household's time zone are taken from each new /me answer before any screen renders (not
 *  on every render, so a switch just saved isn't undone by a navigation), and a device's old choice is adopted once. */
export function RequireAuth() {
  const me = useMe();
  const loc = useLocation();
  const qc = useQueryClient();
  const taken = useRef<unknown>(null);
  if (me.data && taken.current !== me.data) {
    taken.current = me.data;
    setPersonPrefs(me.data.user.prefs);
    setGatewayName(me.data.gateway_name);
    setHouseholdZone(me.data.timezone);   // issue #26: every today is the household's
  }
  useEffect(() => {
    if (me.data) void adoptPrefs(me.data.user.prefs).then((sent) => { if (sent) void qc.invalidateQueries({ queryKey: ['me'] }); });
  }, [me.data, qc]);
  if (me.isPending) return <div aria-busy="true" data-testid="auth-loading" />;
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) {
      return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
    }
    return (
      <div role="alert">
        <p>{me.error.message}</p>
        <button type="button" onClick={() => me.refetch()}>Try again</button>
      </div>
    );
  }
  return <Outlet />;
}
