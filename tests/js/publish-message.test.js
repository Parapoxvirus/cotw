// Tests for the commit message of the GitHub snapshot commit (tools/publish/commit-message.js,
// docs/PUBLISHING.md). Run: node --test tests/js/*.test.js
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');

const SCRIPT = path.join(__dirname, '..', '..', 'tools', 'publish', 'commit-message.js');
const { buildMessage, InputError } = require(SCRIPT);

const PUBLISHER = '112774082+Parapoxvirus@users.noreply.github.com';
const DAWID = 'dawidjasiczek <24965460+dawidjasiczek@users.noreply.github.com>';
const JUERGEN = 'Jürgen Groß <juergen.gross@example.com>';
const ERIKA = 'Erika Muster <erika.muster@example.com>';
const build = (coAuthors, message = 'Countries of the World (COTW)') =>
  buildMessage({ message, coAuthors, publisherEmail: PUBLISHER });

test('without co-authors the message is the input plus a newline', () => {
  assert.equal(build(''), 'Countries of the World (COTW)\n');
  assert.equal(build(undefined), 'Countries of the World (COTW)\n');
  assert.equal(build(' \n ; , '), 'Countries of the World (COTW)\n');
  assert.equal(build('', '  Polish translation  '), 'Polish translation\n');
});

test('one co-author becomes a trailer after a blank line', () => {
  assert.equal(build(DAWID, 'Polish translation'),
    `Polish translation\n\nCo-authored-by: ${DAWID}\n`);
});

test('newline, semicolon and comma all separate entries; one contiguous block', () => {
  const block = `Co-authored-by: ${DAWID}\nCo-authored-by: ${JUERGEN}\nCo-authored-by: ${ERIKA}\n`;
  for (const sep of ['\n', '\r\n', ';', ',', ' ; ', ',\n']) {
    assert.equal(build([DAWID, JUERGEN, ERIKA].join(sep), 'M'), `M\n\n${block}`, JSON.stringify(sep));
  }
});

test('whitespace is normalized and a pasted trailer prefix is accepted', () => {
  assert.equal(build('  Jürgen Groß<juergen.gross@example.com>  '), `Countries of the World (COTW)\n\nCo-authored-by: ${JUERGEN}\n`);
  assert.equal(build(`co-authored-by: ${DAWID}`, 'M'), `M\n\nCo-authored-by: ${DAWID}\n`);
});

test('duplicates (by email, any case) and the publisher are dropped, order kept', () => {
  const input = [ERIKA, DAWID, 'E. Muster <Erika.Muster@Example.com>', `Parapoxvirus <${PUBLISHER}>`, ERIKA].join('\n');
  assert.equal(build(input, 'M'), `M\n\nCo-authored-by: ${ERIKA}\nCo-authored-by: ${DAWID}\n`);
  assert.equal(build(`Parapoxvirus <${PUBLISHER.toUpperCase()}>`, 'M'), 'M\n');
});

test('invalid entries fail, naming the entry', () => {
  const bad = [
    'dawidjasiczek',
    'dawidjasiczek 24965460+dawidjasiczek@users.noreply.github.com',
    '<erika.muster@example.com>',
    'Erika Muster <erika.muster.example.com>',
    'Erika Muster <erika@muster@example.com>',
    'Erika Muster <erika.muster@example>',
    'Erika Muster <erika muster@example.com>',
    'Erika Muster <>',
    'Erika <Muster> <erika.muster@example.com>',
    'Erika Muster <erika.muster@example.com> trailing',
    '$(id) <erika.muster@example.com>',
    '`id` <erika.muster@example.com>',
    'Erika Muster <$(id)@example.com>',
    'Erika Muster <`id`@example.com>',
    'Erika "E" Muster <erika.muster@example.com>',
    'Erika\tMuster <erika.muster@example.com>',
    'Erika\u0000Muster <erika.muster@example.com>',
  ];
  for (const entry of bad) {
    assert.throws(() => build(`${DAWID}\n${entry}`), (e) => e instanceof InputError && e.message.includes(JSON.stringify(entry.trim())), entry);
  }
});

test('a newline cannot smuggle a second trailer or a fake entry into a valid one', () => {
  // Every line is its own entry, so the injected line must itself be a valid `Name <email>`.
  assert.throws(() => build(`Erika Muster\nSigned-off-by: x <erika.muster@example.com>`), InputError);
  assert.throws(() => build(`Erika Muster <erika.muster@example.com\n>`), InputError);
});

test('the message must be a single, non-empty line', () => {
  for (const message of ['', '   ', 'Title\n\nCo-authored-by: ' + DAWID, 'Title\r\nBody', 'Title\rx', 'a b', 'a\u0007b']) {
    assert.throws(() => build('', message), InputError, JSON.stringify(message));
  }
});

test('git recognizes the trailers', () => {
  const message = build([DAWID, JUERGEN].join(','), 'Polish translation');
  const parsed = execFileSync('git', ['interpret-trailers', '--parse'], { input: message, encoding: 'utf8' });
  assert.equal(parsed, `Co-authored-by: ${DAWID}\nCo-authored-by: ${JUERGEN}\n`);
  const none = execFileSync('git', ['interpret-trailers', '--parse'], { input: build(''), encoding: 'utf8' });
  assert.equal(none, '');
});

test('command line: writes the file from the environment, fails with ::error:: before writing', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cotw-publish-'));
  try {
    const out = path.join(dir, 'msg');
    const env = { PATH: process.env.PATH, MESSAGE: 'Polish translation', CO_AUTHORS: DAWID, AUTHOR_EMAIL: PUBLISHER };
    execFileSync(process.execPath, [SCRIPT, out], { env });
    assert.equal(fs.readFileSync(out, 'utf8'), `Polish translation\n\nCo-authored-by: ${DAWID}\n`);

    const bad = path.join(dir, 'bad');
    const r = spawnSync(process.execPath, [SCRIPT, bad], { cwd: dir, env: { ...env, CO_AUTHORS: '$(touch pwned) <x@example.com>' }, encoding: 'utf8' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /^::error::invalid co_authors entry: "\$\(touch pwned\) <x@example\.com>"/);
    assert.equal(fs.existsSync(bad), false);
    assert.equal(fs.existsSync(path.join(dir, 'pwned')), false);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
