import type { HtmlTagDescriptor, Plugin } from 'vite';

/** Issue #25: the two faces the first screen draws with, Newsreader's latin variable face (Home's headline and money
 *  figures) and Source Sans 3's latin 400 (the body text). Fontsource's CSS names them, so a browser finds them only
 *  after that CSS is parsed and text has already painted in the fallback. Vite hashes their file names, so the
 *  preload links are written here, from the build's own file list. */
export const ABOVE_THE_FOLD: readonly RegExp[] = [
  /^assets\/newsreader-latin-wght-normal-[\w-]+\.woff2$/,
  /^assets\/source-sans-3-latin-400-normal-[\w-]+\.woff2$/,
];

/** One preload link per pattern. A pattern that matches no file, or more than one, fails the build: a Fontsource
 *  rename must not quietly drop a preload. */
export function fontPreloads(fileNames: readonly string[], base: string, patterns: readonly RegExp[] = ABOVE_THE_FOLD): HtmlTagDescriptor[] {
  return patterns.map((re) => {
    const found = fileNames.filter((f) => re.test(f));
    if (found.length !== 1) throw new Error(`preload-fonts: ${found.length} files match ${re}, expected 1`);
    return { tag: 'link', attrs: { rel: 'preload', href: `${base}${found[0]}`, as: 'font', type: 'font/woff2', crossorigin: true }, injectTo: 'head' };
  });
}

/** The Vite plugin: at build time, the preload links go into index.html's head. The dev server has no hashed files and
 *  needs none. */
export function preloadFonts(): Plugin {
  let base = '/';
  return {
    name: 'steward-preload-fonts',
    apply: 'build',
    configResolved(config) { base = config.base; },
    transformIndexHtml: {
      order: 'post',
      handler: (_html, ctx) => (ctx.bundle ? fontPreloads(Object.keys(ctx.bundle), base) : []),
    },
  };
}
