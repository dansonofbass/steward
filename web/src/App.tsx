import { QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { setUnauthorizedHandler } from './api/client';
import { queryClient } from './queryClient';
import { router, routes } from './routes';
import { startWarming } from './warm';

setUnauthorizedHandler(() => {
  queryClient.clear();
  if (location.pathname === '/login') return;   // the warm-up's several 401s: the first already sent us to sign-in
  router.navigate('/login?next=' + encodeURIComponent(location.pathname + location.search));
});

// Phase 18: the opening screen's data and code start now, beside /me, and each later address's as the router reaches it.
startWarming(router, routes, queryClient);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
