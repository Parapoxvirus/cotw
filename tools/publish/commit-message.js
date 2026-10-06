/*
 * Commit message of the GitHub snapshot commit (.gitea/workflows/publish.yml, docs/PUBLISHING.md):
 * the one-line `message` input, then, after a blank line, one `Co-authored-by:` trailer per
 * entry of the `co_authors` input. Inputs come from the environment only, never from the shell.
 *
 *   MESSAGE=… CO_AUTHORS=… AUTHOR_EMAIL=… node tools/publish/commit-message.js <file>
 *
 * Any invalid input fails the run before anything is pushed.
 */
'use strict';

const fs = require('node:fs');

const TRAILER = 'Co-authored-by';
// Control characters, and the characters that are unsafe or ambiguous in a name.
const CONTROL = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/;
const NAME_FORBIDDEN = /[<>,;"\\`$]/;
// Deliberately narrower than RFC 5322; covers GitHub noreply addresses (id+login@users.noreply.github.com).
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$/;
const ENTRY = /^(.*?)\s*<([^<>]*)>$/;

class InputError extends Error {}

function checkMessage(message) {
  const text = (message || '').trim();
  if (!text) throw new InputError('message is empty');
  if (/[\r\n]/.test(text)) {
    throw new InputError(`message must be a single line (co-authors go into co_authors): ${JSON.stringify(text)}`);
  }
  if (CONTROL.test(text)) throw new InputError(`message contains a control character: ${JSON.stringify(text)}`);
  return text;
}

// `Name <email>` entries separated by newlines, `;` or `,`; a pasted `Co-authored-by:` prefix is accepted.
function parseCoAuthors(input) {
  const people = [];
  const errors = [];
  for (const raw of (input || '').split(/[\r\n;,]+/)) {
    const entry = raw.trim().replace(new RegExp(`^${TRAILER}:\\s*`, 'i'), '');
    if (!entry) continue;
    const m = ENTRY.exec(entry);
    const name = m ? m[1].trim() : '';
    const email = m ? m[2].trim() : '';
    let problem = null;
    if (!m) problem = 'expected `Name <email>`';
    else if (!name) problem = 'name is empty';
    else if (CONTROL.test(name) || NAME_FORBIDDEN.test(name)) problem = 'name contains one of , ; < > " \\ ` $ or a control character';
    else if (!EMAIL.test(email)) problem = 'invalid email address';
    if (problem) errors.push(`${JSON.stringify(entry)}: ${problem}`);
    else people.push({ name, email });
  }
  if (errors.length) throw new InputError(`invalid co_authors entry: ${errors.join('; ')}`);
  return people;
}

// Deduplicated by email (case-insensitive, first entry wins); the publisher itself is dropped.
function buildMessage({ message, coAuthors, publisherEmail } = {}) {
  const subject = checkMessage(message);
  const seen = new Set(publisherEmail ? [publisherEmail.trim().toLowerCase()] : []);
  const trailers = [];
  for (const { name, email } of parseCoAuthors(coAuthors)) {
    const key = email.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    trailers.push(`${TRAILER}: ${name} <${email}>`);
  }
  return trailers.length ? `${subject}\n\n${trailers.join('\n')}\n` : `${subject}\n`;
}

function main(argv, env) {
  const out = argv[2];
  if (!out) throw new InputError('usage: node commit-message.js <output file>');
  const text = buildMessage({ message: env.MESSAGE, coAuthors: env.CO_AUTHORS, publisherEmail: env.AUTHOR_EMAIL });
  fs.writeFileSync(out, text);
}

if (require.main === module) {
  try {
    main(process.argv, process.env);
  } catch (e) {
    if (!(e instanceof InputError)) throw e;
    console.error(`::error::${e.message}`);
    process.exit(1);
  }
}

module.exports = { buildMessage, parseCoAuthors, checkMessage, InputError };
