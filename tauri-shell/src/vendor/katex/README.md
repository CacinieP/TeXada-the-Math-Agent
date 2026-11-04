# Vendored KaTeX

Version: **0.18.2**, pinned in the root `package.json` and `package-lock.json`.

`katex.min.js`, `katex.min.css`, `fonts/`, and `LICENSE` are unmodified files from
[the official npm release](https://www.npmjs.com/package/katex/v/0.18.2).
The lockfile records the registry archive and its SHA-512 integrity value.

This version fixes [GHSA-238p-pmpm-9mq7](https://github.com/KaTeX/KaTeX/security/advisories/GHSA-238p-pmpm-9mq7).
The [upstream release notes](https://github.com/KaTeX/KaTeX/releases/tag/v0.18.2)
describe the inherited-setting checks. Do not replace only the npm dependency:
the application uses these bundled files at runtime, including offline.

The Python wheel maps this same JavaScript file to
`texada/semantic/vendor/katex.min.js`; the desktop sidecar build copies it to the
same package path. The frontend CSS and fonts remain together in this directory.

After `npm ci`, `node --test tests/katex-assets.test.cjs` checks the version,
byte-for-byte npm asset identity, font references, representative rendering, and
prototype-pollution trust restrictions. Updating the parser version also requires
the Python structural allowlist and semantic regression tests to be revalidated.
