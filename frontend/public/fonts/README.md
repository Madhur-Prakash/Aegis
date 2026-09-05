# Fonts

The two families named in `docs/UI_MOTION.md` §00 2.1, self-hosted. Declared in
`app/fonts.css`; the family names there are the literal ones `design/tokens.css`
asks for, which is why these are plain `@font-face` rules and not
`next/font/local` (see `docs/DECISIONS.md`).

| File | Family | Weight | Source | Licence |
|---|---|---|---|---|
| `satoshi-{300,500,700,900}.woff2` | Satoshi | 300 / 500 / 700 / 900 | [Fontshare](https://www.fontshare.com/fonts/satoshi) (Indian Type Foundry) | ITF Free Font Licence — free for personal and commercial use, redistribution permitted as part of a design |
| `jetbrainsmono-{400,500,700}-{latin,latinext}.woff2` | JetBrains Mono | 400 / 500 / 700 | [Google Fonts](https://fonts.google.com/specimen/JetBrains+Mono) | SIL Open Font Licence 1.1 |

Only the Latin and Latin-Extended subsets of the mono face are here: the mono
family sets labels, ids, hashes and numerals, which stay Latin in both locales
(Hindi included — Indian financial interfaces use Latin numerals with Indian
grouping). The Cyrillic, Greek and Vietnamese subsets Google serves would be
about 90 KB nothing in this product can render.

Total: 10 files, ~245 KB, all preloaded or swapped in behind the fallback stack.

## Refetching

```sh
# Satoshi
curl -s "https://api.fontshare.com/v2/css?f[]=satoshi@300,500,700,900&display=swap"
# JetBrains Mono
curl -s "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap"
```

Both return `@font-face` blocks; take the `.woff2` URL from each and keep the
`unicode-range` on the mono faces unchanged — `app/fonts.css` repeats them, and
a mismatch would download a subset the browser then cannot use.
