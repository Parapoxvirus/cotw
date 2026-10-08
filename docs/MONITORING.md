# Change monitoring

Step 5 of the [roadmap](ROADMAP.md), decisions **15** and **E · Flags** in
[`DECISIONS.md`](DECISIONS.md): a weekly job compares what the database took from Wikidata and
Wikimedia Commons with the live state and opens **one Gitea issue per change** (or one task in a
Paperclip project, see [Paperclip sink](#paperclip-sink)). With the Paperclip sink it also
watches the **Wikidata names** and the **official naming sources** for changes (see
[Names and naming sources](#names-and-naming-sources)). Nothing is applied automatically;
every issue is accepted or rejected by hand.

## How it runs

- Workflow [`.gitea/workflows/wikidata-check.yml`](../.gitea/workflows/wikidata-check.yml):
  every Monday at 04:17 UTC, plus `workflow_dispatch` for manual runs (input `dry_run`,
  default on). Same runner setup as `ci.yml` (`node:20-bookworm` with apt `python3`).
- Command: `python -m cotw check-wikidata [--dry-run] [--max-issues N]` (network).
  Without a token it is always a dry run, so running it locally never writes anything:

  ```bash
  .venv/bin/python -m cotw check-wikidata --dry-run
  ```

- All reads (Wikidata, Commons, the damping look-ups, the existing issues or the Paperclip
  state) happen before the first write. A network failure fails the job and opens no issue.
- Wikimedia etiquette: the requests carry the `User-Agent` from `COTW_USER_AGENT` (default
  `cotw-build/1.0 (https://github.com/Parapoxvirus/cotw)`, as for the flags), queries are
  batched (25–150 items per SPARQL query, 50 per API call), and 429/5xx answers are retried with
  a growing back-off. A run needs a few dozen requests.

## Baseline: the committed caches

The check compares against the **caches** in `data/wikidata/` and the flag manifest
`data/derived/flags.yaml`, not against the YAML database. The caches are the last accepted
snapshot, so only what changed upstream since then is reported; differences between the
database and Wikidata that were decided during the import (overrides, spreadsheet values) do
not come back.

| What | Wikidata / Commons | Baseline | Reported when |
|---|---|---|---|
| ISO 3166-1 alpha-3 | P298 of the entry's item | `countries.json` | the code changes |
| Capitals | P36 with role qualifiers (P3831/P518), rank, end time (P582) | `capitals.json` | the set of places that count changes: non-deprecated statements without an end time, with their role |
| Capital coordinates | P625 of every capital the database uses | `capitals.json` + `places.json` | the point moves more than **1 km** (float noise and refinements stay quiet) or disappears |
| The entry's own status | dissolved (P576), end time (P582) | `status.json` | a value appears, changes or goes away |
| Wikipedia links | `enwiki` / `dewiki` sitelinks | `sitelinks.json` | the article title changes or the article goes away |
| Flag selection | P41 (rank, end time), picked like `fetch-flags` does | `flags.json` | the picked file changes or becomes ambiguous |
| Flag file | Commons file revision (SHA-1) | `data/derived/flags.yaml` | a new revision is uploaded, or the file is deleted/renamed |
| Flag license | Commons `LicenseShortName` | `data/derived/flags.yaml` | the license changes; a file that is **no longer public domain/CC0** is flagged *NON-FREE* and filed first |
| Scope | P297 on any item | `iso-codes.json` | an entry's item loses its code (entry to retire?), another item gains an entry's code, or a code outside the deck appears (new entry candidate) |

Names are not in this table: the database's names come from the official naming sources of
[`TRANSLATING.md`](TRANSLATING.md), not from Wikidata, so there is no cache to compare. Name
changes on Wikidata and new editions of the naming sources are watched separately, against a
baseline of the values last seen (see [Names and naming sources](#names-and-naming-sources)).

A flag file shared by several entries (the tricolor of the French overseas departments, …) is
one deviation, listing every entry that uses it.

### Decided deviations are not reported

- `data/overrides/capitals.yaml`: capitals whose coordinates are fixed there (`lat`/`lon`) are
  not compared.
- `data/overrides/flags.yaml`: an entry with a fixed `file` ignores P41 changes (the file's
  Commons revision and license are still watched); an accepted `license` does not raise the
  non-free alert.
- `data/overrides/wikidata.yaml`: the check follows the item the override picked.
- `data/overrides/monitoring.yaml`: rejected deviations, by fingerprint (see *Reject*).

### Vandalism damping (72 h)

A value whose latest change is less than **72 hours** old is not reported; it is picked up by
the next weekly run if it survives. Concretely: when the item was edited within the last 72 h,
the check loads the item as it was 72 h ago and compares the part the deviation depends on (the
claims of the property, or the sitelink). If that part differs, the change is recent and waits
a week; if it is the same, the change is older and the recent edit touched something else
(busy items such as Q183 would otherwise never be reported). For Commons files the latest page
edit or upload counts. Damped deviations are listed in the job log.

## Issues

- One issue per deviation, label **`wikidata`**, never `agent`: approval stays manual.
- Title: entry and what changed. Body: entry (COTW id and name), field, old → new value, links
  to the Wikidata item and its revision history (and the Commons file page and history for
  flags), what would change in the deck, and the exact commands to accept or reject it.
- **Fingerprint**: 16 hex digits of `sha256(subject, field, new value)`, in a hidden comment
  `<!-- cotw-monitor fingerprint=… -->`. If an **open or closed** issue already carries the
  fingerprint, nothing is filed. A closed issue means decided and is not reopened. If the value
  changes again, the fingerprint changes and a new issue opens.
- **Flood cap**: at most `--max-issues` (default 20) new issues per run, non-free flags first.
  The rest go into one summary issue, which later runs update in place (never a second one) and
  close once everything is filed.

### Token

The workflow passes `secrets.COTW_MONITOR_TOKEN` if that repository secret exists, otherwise
the built-in Actions token (`github.token`, with `permissions: issues: write` requested). The
tool reads it from the environment variable `COTW_MONITOR_TOKEN` and never prints it; the log
shows only the permissions the token has on the repository.

If the built-in token may not create issues (the run fails with HTTP 401/403), create the
secret: a Gitea access token of an account with write access to this repository, scopes
**`write:issue`** and **`read:repository`**, stored as repository secret
`COTW_MONITOR_TOKEN` (*Settings → Actions → Secrets*). With the Paperclip sink the token also
writes the state branch: the workflow requests `permissions: contents: write`, and a secret
needs **`write:repository`** instead of `read:repository`.

## Paperclip sink

Instead of Gitea issues the monitor can create **tasks in a Paperclip
project**. It is selected when all four of these are set; otherwise nothing changes:

| Variable | Workflow source | Meaning |
|---|---|---|
| `PAPERCLIP_API_URL` | `vars.PAPERCLIP_API_URL` | API base, ending in `/api` (e.g. `https://paperclip.example.com/api`) |
| `PAPERCLIP_API_KEY` | `secrets.PAPERCLIP_TASK_KEY` | key sent as `Authorization: Bearer …`, never printed |
| `PAPERCLIP_COMPANY_ID` | `vars.PAPERCLIP_COMPANY_ID` | company the tasks are created in |
| `PAPERCLIP_PROJECT_ID` | `vars.PAPERCLIP_PROJECT_ID` | project the tasks are created in |
| `PAPERCLIP_ASSIGNEE_AGENT_ID` | `vars.PAPERCLIP_ASSIGNEE_AGENT_ID` | optional: agent the tasks are assigned to |
| `COTW_MONITOR_STATE_BRANCH` | `vars.COTW_MONITOR_STATE_BRANCH` | optional: state branch (default `cotw-monitor-state`) |
| `COTW_MONITOR_NOTIFY_ISSUE` | `vars.COTW_MONITOR_NOTIFY_ISSUE` | optional: issue identifier the [digest task](#digest-task) asks to comment on; unset: no digest |

Each task has the title and description an issue would have (fingerprint marker included) and
starts as `todo`. The key only needs to **create tasks and read the tasks it created**; a
restricted task bridge key that cannot list, update or comment is enough.

**State branch.** Such a key cannot search the project for a fingerprint, so the monitor keeps
what it filed in `cotw-monitor-state.json` on the branch `cotw-monitor-state` of this
repository, read and written with the Gitea contents API and `COTW_MONITOR_TOKEN`. The branch is
created from the default branch on the first write; nobody merges it.

```json
{"version": 2,
 "filed":   {"<fingerprint>": {"task_id": "…", "identifier": "ABC-12", "title": "…", "filed_at": "…"}},
 "decided": {"<fingerprint>": {"source": "paperclip-done:ABC-12", "decided_at": "…"}},
 "summary": {"task_id": "…", "identifier": "ABC-13"},
 "names":   {"Q697": {"labels/en": "Nauru", "labels/de-ch": null, "labels/de": "Nauru", "P1448": ["en: Republic of Nauru", "na: Repubrikin Naoero"]}},
 "sources": {"eda": {"signature": {"sha256": "…", "size": 133891}, "since": "…"},
             "stagn": {"signature": {"documents": ["…/STAATENNAMEN_15.pdf"]}, "since": "…",
                       "failures": 1, "failing_since": "…", "error": "…"}}}
```

`names` and `sources` are the baselines of the name and naming-source checks. A version 1
file (before these checks) is read as version 2 with both empty, i.e. the next run seeds them.

Every run:

1. reads the state and the status of every `filed` task. **Done or cancelled** (or another
   terminal status, or deleted) moves the fingerprint to `decided`: like a closed issue, it is
   never filed again. Accept or reject the change as below, then close or cancel the task;
2. checks the names and the naming sources against the baselines in the state (see
   [Names and naming sources](#names-and-naming-sources)); their findings join the deviations;
3. files tasks for deviations whose fingerprint is neither filed nor decided, at most
   `--max-issues`, non-free flags first;
4. puts the rest into one summary task. The key cannot update a task, so the summary is filed
   once and left alone; when it is closed and deviations are still waiting, the next run files a
   new one;
5. writes the state in one commit, also when creating a task failed halfway, so a created task
   is never filed twice;
6. files the [digest task](#digest-task) if it filed at least one task.

A dry run reads the state and the task statuses and writes nothing. Without
`COTW_MONITOR_TOKEN` (or repository/URL) there is no state, so it is always a dry run.

### Digest task

The task bridge key cannot comment, so the monitor cannot post a note anywhere itself. Instead
a run that filed **at least one** task (findings or the summary) files **one digest task**,
assigned like the others (`PAPERCLIP_ASSIGNEE_AGENT_ID`):

- title `cotw monitor: N new findings (YYYY-MM-DD)`;
- description: the instruction to post the summary as **one comment on the issue named in
  `COTW_MONITOR_NOTIFY_ISSUE`** and then mark the digest done, followed by the summary (one
  line per task filed in this run, identifier and title, plus the number still waiting).

No digest when the run filed nothing, in a dry run, with `COTW_MONITOR_NOTIFY_ISSUE` unset, or
with the Gitea issue sink. The digest carries no fingerprint and is not kept in the state; a
failure to create it is logged and does not affect the state write.

### Switching from issues to tasks

Issues filed before the switch must not come back as tasks. Once, before the first real run
with the Paperclip sink, seed the state with every fingerprint found in the repository's issues:
closed ones as `gitea-closed:<number>`, open ones as `gitea-open:<number>` (migrate those by
hand). Both count as decided. The import is idempotent and a dry run without `--apply`:

```bash
.venv/bin/python -m cotw import-monitor-issues          # preview
.venv/bin/python -m cotw import-monitor-issues --apply  # write the state branch
```

It needs `GITHUB_SERVER_URL`/`GITHUB_REPOSITORY` (or `--gitea-url`/`--repo`) and
`COTW_MONITOR_TOKEN`. In CI: run the workflow by hand with `import_issues` on (and `dry_run`
off to write).

## Names and naming sources

Two checks that need a baseline the repository does not hold. They run only with the
Paperclip sink, whose state branch holds the baselines (`names`, `sources`); with the Gitea
issue sink, or without access to the state branch, they are skipped with one log line.

**A Wikidata label is a signal, not a source.** Neither check changes a name; every finding
asks for a check against the official list of the language in
[`TRANSLATING.md`](TRANSLATING.md#naming-sources) and for applying official changes as soon as
possible (its *Source rule*).

### What is watched

- **Names on Wikidata**, for every entry item and every capital item the deck uses
  (`capitals[].wikidata`): the label in every Wikidata language that a registered locale reads
  (its `wikidata` chain in `data/locales.yaml`: en-US `en`, de-CH `de-ch` then `de`; a new
  locale is picked up without code changes), and for entry items the current
  official names **P1448** (all languages, non-deprecated, without end time), as
  `"<language>: <name>"`. A change of the capital statement itself (P36) is a *capitals*
  deviation (table above).
- **Official naming sources** of [`TRANSLATING.md`](TRANSLATING.md#naming-sources), through a
  signature that changes with a new edition or update and ignores volatile page parts (session
  ids, navigation, generated element ids). A page is never compared by its raw hash.

| Id | Source | Languages | Signature |
|---|---|---|---|
| `eda` | Liste der Staatenbezeichnungen (EDA) | de-CH | the PDF: SHA-256 and size (`ETag`/`Last-Modified` are shown, not compared) |
| `auswaertiges-amt` | Verzeichnis der Staatennamen für den amtlichen Gebrauch (Auswärtiges Amt) | de-CH | the linked documents (PDF, XLSX, ODS) |
| `stagn` | Liste der Staatennamen und ihrer Ableitungen im Deutschen (StAGN) | de-CH | the linked documents (the edition is in the file name) |
| `bk-schreibweisungen` | Schreibweisungen (Swiss Federal Chancellery) | de-CH | the linked documents |
| `bk-rechtschreibleitfaden` | Rechtschreibleitfaden (Swiss Federal Chancellery) | de-CH | the linked documents |
| `ksng-states` | Urzędowy wykaz nazw państw i terytoriów niesamodzielnych (KSNG) | pl-PL | the linked attachments (list and its update documents) |
| `ksng-world` | Urzędowy wykaz polskich nazw geograficznych świata (KSNG) | pl-PL | the linked attachments (list and its list of changes) |
| `funag-toponimos` | Topônimos e gentílicos (FUNAG, official accessible reproduction) | pt-BR | the table cell texts (SHA-256) and the row count |
| `pcgn-country-names` | Country names (PCGN, GOV.UK) | en-US | GOV.UK content API: `public_updated_at` and the attachments |
| `fcdo-geographical-names` | Geographical names index (FCDO with PCGN, GOV.UK) | en-US | GOV.UK content API: `public_updated_at` and the attachments |
| `eu-annex-a5-en`, `eu-annex-a5-de`, `eu-annex-a5-pl` | Interinstitutional Style Guide, Annex A5 (Publications Office of the EU) | en-US, de-CH, pl-PL (the EU language `en`, `de`, `pl` is the locale's language) | the table cell texts (SHA-256) and the row count |

The records live in `tools/cotw/monitor_sources.py`; every one has a test with a recorded
response. Not watched, with the reason (a test keeps this list and `TRANSLATING.md` in step):

| Source | Why not |
|---|---|
| [Manual de redação oficial e diplomática do Itamaraty](https://www.gov.br/mre/pt-br/arquivos/manual-de-redacao) | the MRE page challenges automated clients; its official accessible FUNAG reproduction is watched instead |
| [UNTERM](https://unterm.un.org/) | a JavaScript application without a documented public API; UN renamings also reach Wikidata, the national lists and the EU list, which are watched |
| [Independent States in the World](https://www.state.gov/independent-states-in-the-world/) | the State Department site refuses automated clients (HTTP 403) |
| [Dependencies and Areas of Special Sovereignty](https://www.state.gov/dependencies-and-areas-of-special-sovereignty/) | the State Department site refuses automated clients (HTTP 403) |
| [ISO 3166-1](https://www.iso.org/iso-3166-country-codes.html) | iso.org refuses automated clients (HTTP 403) and the Online Browsing Platform needs JavaScript; the codes are watched through P297/P298 |

The pl-PL and pt-BR sources are watched although the deck has no package in those locales yet:
the names will be checked against them when it does. The languages of a source are locales of
`data/locales.yaml`, and a finding links their sections of `TRANSLATING.md`.

### Baseline

The baseline is **what Wikidata (or the source) said last time**, never the database's names.
The known, documented differences between COTW and Wikidata therefore never show up.

- A key missing from the baseline is **seeded silently**: the first run, a new locale or a new
  language in a locale's chain, a new entry or capital, a new source. The log states how many
  keys were seeded.
- The label keys are **Wikidata languages** (`labels/en`, `labels/de-ch`, `labels/de`), not
  locales, so the baseline written before the locale codes (`labels/en`, `labels/de`) is used
  as it is: no migration, `labels/de-ch` is seeded silently on the first run after the
  change, and unchanged values give no finding (a test runs that case). A finding links the
  `TRANSLATING.md` sections of the locales that read the changed language (`de` → de-CH).
- A key whose live value differs from the baseline, or that disappeared (a removed label), is a
  finding.
- The baseline moves to the live value for unchanged keys and for the keys of a finding that
  was filed in this run (or filed or decided before, or rejected in `monitoring.yaml`).
  Findings that are damped or wait in the summary keep their old baseline, so they come back
  on the next run. Keys no longer watched are dropped. A dry run writes nothing.
- **Damping** (72 h, as above) applies to name findings per changed part (`labels/<language>` or
  the P1448 claims); a finding is damped if any of its parts changed within 72 h.

### Findings

- **`names`**: one per entry and run, listing every changed value of the entry and its capitals
  as `item · what · language: old → new`. A capital used by several entries is listed under
  each of them (its baseline moves when all of those are filed). Fingerprint: entry, `names`
  and the new values.
- **`edition`**: one per source with a changed signature: old and new signature, the documents
  that appeared or went away, the languages it decides and the link to its section in
  `TRANSLATING.md`. Fingerprint: source id, `edition` and the new signature.
- **`source-unreachable`**: a failed fetch of an official site never fails the job; it is
  logged, the baseline is kept and the failures are counted. After **3 consecutive failed
  runs** one finding asks to check the URL. A successful fetch resets the count.

Every `names` and `edition` finding carries the reminder and links to the language sections of
`TRANSLATING.md`. Handling one:

1. compare every changed value with the official list of its language (*Naming sources*);
2. if an official source has the change: edit `name.<code>`, `formal_name` or
   `capitals[].name.<code>` in `data/countries/*.yaml`; deviating from the language's primary
   source needs a row with the reason in [`data-changes.md`](data-changes.md); then
   `validate`, `pytest`, `build-deck` as below;
3. nothing official yet: mark the task done. The baseline has already moved, so the same change
   is not reported again; the official list catches up through an `edition` finding.

There is no cache to accept: `accept-wikidata` does not apply to these findings. A finding can
still be rejected through `monitoring.yaml` like any other.

### Local dry run with a state file

To try the checks without the state branch, run against a local state file:

```bash
.venv/bin/python -m cotw check-wikidata --dry-run --state-file build/monitor-state.json
```

It is always a dry run: no task is filed, task statuses are not read, nothing is written to
the repository. The file is created on the first pass with the seeded baseline (0 name or
source findings); a second pass compares against it. Editing a value in the file's `names` by
hand simulates a change: the next pass prints it as one `[would file]` finding with its
reminder. A finding never moves the baseline in the file.

## Accept a change

For every issue (by hand, or by Flint after an implement command on the issue):

```bash
.venv/bin/python -m cotw accept-wikidata <fingerprint>
```

It re-runs the check, finds the deviation by its fingerprint and updates **only its keys** in
the caches, so other pending deviations stay pending. For the mechanical kinds it also writes
the database field; everything else is a decision it leaves to you and prints as next steps:

| Kind | `accept-wikidata` writes | Then |
|---|---|---|
| ISO-3 | `countries.json`, `iso3` in the entry | |
| Capital coordinates | `capitals.json`/`places.json`, `lat`/`lon` in the entry | `build-maps <id>` |
| Wikipedia link | `sitelinks.json`, `wikipedia.de-CH` (or `.en-US`) in the entry | |
| Capitals (P36) | `capitals.json` | edit `capitals` in the entry if the deck follows, `build-maps <id>` |
| Status (P576/P582) | `status.json` | decide on the entry; never delete it (COTW ids are frozen, DECISIONS A1) |
| Scope (P297) | `iso-codes.json` (`countries.json`) | a new entry needs a YAML file and the next free id in `data/ids.yaml`, maps and a flag; a retired one is never deleted |
| Flag selection (P41) | `flags.json` | `fetch-flags --offline-wikidata` |
| Flag revision / license | nothing | `fetch-flags --offline-wikidata` (fails for a non-free license until an override in `data/overrides/flags.yaml` picks a free file or accepts the license with a reason) |

Every accepted change ends with:

```bash
.venv/bin/python -m cotw validate
.venv/bin/python -m pytest          # includes the en-US/de-CH coexistence import test (step 4)
.venv/bin/python -m cotw build-deck
```

Bump nothing by hand: the package timestamp comes from the commit, which is what lets Anki
accept the update. `fetch-flags` rebuilds the whole manifest, so it also takes in other pending
flag revisions/licenses; the issues of those then close with the same PR. Commit the caches,
the entry and the rebuilt media together, with `Fixes #<issue>` in the PR.

Refreshing a whole cache (`fetch-wikidata`, `fetch-wikipedia`) accepts **every** pending change
of that cache at once; do it only when all open `wikidata` issues are decided.

## Reject a change

Add the fingerprint with a reason to `data/overrides/monitoring.yaml` and close the issue:

```yaml
rejected:
  'c1fb13c11236ae10':
    subject: '083'
    field: iso3
    reason: the deck keeps the ISO code the standard publishes
```

The caches keep the old value; the rejected deviation is never reported again, a further change
of the same field is.
