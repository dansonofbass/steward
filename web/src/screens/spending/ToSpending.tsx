import { useLocation } from 'react-router-dom';
import { Navigate } from '../../book/links';

/** Cash flow became Spending (decision 2): an old /cashflow address keeps its query. */
export function ToSpending() {
  const { search } = useLocation();
  return <Navigate to={`/spending${search}`} replace />;
}
