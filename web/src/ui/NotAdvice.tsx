export const NOT_ADVICE = 'Estimates, not financial or tax advice.';

/** The line at the foot of Plan, Taxes and Business, and on About. */
export function NotAdvice() {
  return <p className="small muted">{NOT_ADVICE}</p>;
}
