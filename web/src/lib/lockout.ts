/** Minutes to wait, read from the server's "Try again in N minute(s)." message. Falls back to the 15-minute lockout. */
export function lockoutMinutes(message: string): number {
  const m = /in (\d+) minutes?/.exec(message);
  const n = m ? Number(m[1]) : NaN;
  return n > 0 ? n : 15;
}
