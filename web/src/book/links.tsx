// Link, Navigate and useNavigate for screens inside a book. They take the same props as react-router's and put an
// absolute in-app path ('/settings/banks', '/cashflow?month=…') in the open book, so screens keep writing the
// paths they always wrote. Sign-in pages, /design and paths already under /b/ are left alone.
import { forwardRef, useCallback } from 'react';
import {
  Link as RouterLink, Navigate as RouterNavigate, useNavigate as useRouterNavigate,
  type LinkProps, type NavigateOptions, type NavigateProps, type To,
} from 'react-router-dom';
import { useBookTo } from './BookContext';

const OUTSIDE = ['/b/', '/login', '/forgot', '/reset', '/design'];

export function inBook(to: To, prefix: (path: string) => string): To {
  if (typeof to !== 'string' || !to.startsWith('/') || OUTSIDE.some((o) => to.startsWith(o))) return to;
  return prefix(to);
}

export const Link = forwardRef<HTMLAnchorElement, LinkProps>(function BookLink({ to, ...rest }, ref) {
  const prefix = useBookTo();
  return <RouterLink ref={ref} to={inBook(to, prefix)} {...rest} />;
});

export function Navigate({ to, ...rest }: NavigateProps) {
  const prefix = useBookTo();
  return <RouterNavigate to={inBook(to, prefix)} {...rest} />;
}

export function useNavigate() {
  const navigate = useRouterNavigate();
  const prefix = useBookTo();
  return useCallback((to: To | number, options?: NavigateOptions) => {
    if (typeof to === 'number') return navigate(to);
    return navigate(inBook(to, prefix), options);
  }, [navigate, prefix]);
}
