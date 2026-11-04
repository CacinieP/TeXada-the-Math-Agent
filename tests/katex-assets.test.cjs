'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const vendor = path.join(root, 'tauri-shell', 'src', 'vendor', 'katex');
const upstream = path.join(root, 'node_modules', 'katex');
const source = fs.readFileSync(path.join(vendor, 'katex.min.js'), 'utf8');
const version = '0.18.2';

function browserBuild() {
  // A fresh realm also isolates deliberately polluted prototypes from Node.
  const context = vm.createContext({ console: { warn() {}, log() {} } });
  vm.runInContext(source, context);
  return context;
}

function render(expression, extra = {}) {
  const context = browserBuild();
  context.input = expression;
  context.options = { throwOnError: true, strict: 'ignore', maxExpand: 1000,
    macros: { '\\placeholder': '\\square' }, ...extra };
  return vm.runInContext('katex.renderToString(input, options)', context);
}

test('npm lock and the runtime browser build pin the same patched KaTeX version', () => {
  const metadata = JSON.parse(fs.readFileSync(path.join(root, 'package.json')));
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'package-lock.json')));
  assert.equal(metadata.devDependencies.katex, version);
  assert.equal(lock.packages[''].devDependencies.katex, version);
  assert.equal(lock.packages['node_modules/katex'].version, version);
  assert.equal(vm.runInContext('katex.version', browserBuild()), version);
  const html = fs.readFileSync(path.join(root, 'tauri-shell', 'src', 'index.html'), 'utf8');
  assert.ok(html.includes(`vendor/katex/katex.min.js?v=${version}`));
  assert.ok(html.includes(`vendor/katex/katex.min.css?v=${version}`));
});

test('offline JavaScript, CSS, license and every font match the official npm distribution', () => {
  for (const filename of ['katex.min.js', 'katex.min.css']) {
    assert.deepEqual(fs.readFileSync(path.join(vendor, filename)),
      fs.readFileSync(path.join(upstream, 'dist', filename)), filename);
  }
  assert.deepEqual(fs.readFileSync(path.join(vendor, 'LICENSE')),
    fs.readFileSync(path.join(upstream, 'LICENSE')));
  const fonts = fs.readdirSync(path.join(upstream, 'dist', 'fonts')).sort();
  assert.deepEqual(fs.readdirSync(path.join(vendor, 'fonts')).sort(), fonts);
  for (const font of fonts) {
    assert.deepEqual(fs.readFileSync(path.join(vendor, 'fonts', font)),
      fs.readFileSync(path.join(upstream, 'dist', 'fonts', font)), font);
  }
  const stylesheet = fs.readFileSync(path.join(vendor, 'katex.min.css'), 'utf8');
  const references = [...stylesheet.matchAll(/url\((?:["']?)([^)"']+)(?:["']?)\)/g)].map(match => match[1]);
  assert.ok(references.length > 0);
  for (const reference of references) {
    assert.ok(reference.startsWith('fonts/'), `font must stay offline: ${reference}`);
    assert.ok(fs.existsSync(path.join(vendor, reference)), `missing font: ${reference}`);
  }
});

test('the browser build still renders formula structures and the application placeholder macro', () => {
  const formulas = [String.raw`\frac{x+1}{x-1}`, String.raw`\sqrt[n]{x}`,
    String.raw`\int_0^1 x^2\,dx`, String.raw`\sum_{i=0}^n a_i`,
    String.raw`\begin{pmatrix}a&b\\c&d\end{pmatrix}`,
    String.raw`f(x)=\begin{cases}x&x>0\\0&x\leq0\end{cases}`,
    String.raw`\iint_D f(x,y)\,dx\,dy`, String.raw`\frac{\placeholder}{2}`];
  for (const formula of formulas) {
    const html = render(formula, { displayMode: true });
    assert.match(html, /class="katex"/);
    assert.doesNotMatch(html, /class="katex-error"/);
  }
  assert.throws(() => render(String.raw`\frac{x}{`), /KaTeX parse error/);
});

test('inherited settings cannot enable trusted links in the bundled runtime', () => {
  // Regression for GHSA-238p-pmpm-9mq7; no DOM is created or script executed.
  const cases = [
    'Object.prototype.trust = true; katex.renderToString(input)',
    'katex.renderToString(input, Object.create({trust: true}))',
    'Object.prototype.default = true; katex.renderToString(input)',
    'Object.prototype.processor = () => true; katex.renderToString(input, {trust: false})',
  ];
  for (const operation of cases) {
    const context = browserBuild();
    context.input = String.raw`\href{javascript:alert(1)}{x}`;
    const html = vm.runInContext(operation, context);
    assert.doesNotMatch(html, /<a\s+href=/, operation);
  }
});
