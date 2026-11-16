// The Node calls the CSS and file tests need; the app's tsconfig doesn't load @types/node.
declare module 'node:fs' {
  export function readFileSync(path: URL | string, encoding: 'utf8'): string;
  export function readFileSync(path: URL | string): Uint8Array;
  export function existsSync(path: URL | string): boolean;
  export function readdirSync(path: URL | string, options: { recursive: true; encoding: 'utf8' }): string[];
}
