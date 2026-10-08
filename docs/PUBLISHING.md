# Publishing to GitHub

COTW is developed on Gitea; the public repository
[`Parapoxvirus/cotw`](https://github.com/Parapoxvirus/cotw) on GitHub receives **snapshots**.
The workflow [`.gitea/workflows/publish.yml`](../.gitea/workflows/publish.yml) (manual
`workflow_dispatch` only, merging never publishes anything) does this:

1. Takes the tree of the dispatched commit (or of `tag`) and creates **one** new commit on top of
   GitHub's `main`, authored by `Parapoxvirus`. The first snapshot has no parent. The internal
   history (commits, authors, trailers) is not published.
2. Pushes that commit to GitHub's `main`, and with `tag` also as that tag.
3. With `tag`, copies the Gitea release of the tag (notes and `.apkg` assets) to a GitHub release.

If GitHub's `main` already has the same tree, no new commit is created (step 2 is then a no-op).

The release assets are the packages of `python -m cotw build-deck`, one per registered locale:
`COTW-EN-US.apkg`, `COTW-DE-CH.apkg`, `COTW-PL-PL.apkg` and `COTW-PT-BR.apkg` (up to v1.0.x
`COTW-EN.apkg` and `COTW-DE.apkg`). The
workflow copies whatever assets the Gitea release has; the README's download line names them.
The notes of the first release with the locale names tell users what changes on update: the
tag roots (`COTW-EN-US::` instead of `COTW-EN::`, filtered decks and saved searches need the
new root), the note type names and the file names; notes and review history are kept
([`DECK.md`](DECK.md#tags)).

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `tag` | empty | Release tag to publish. Empty: the code of the dispatched branch only, no tag, no release. |
| `message` | `Countries of the World (COTW)` | Commit message on GitHub. **One line**; a line break fails the run. |
| `co_authors` | empty | Contributors credited with `Co-authored-by:` trailers, see below. |
| `dry_run` | `false` | `true`: build and print the commit, push nothing, copy no release. |

The inputs reach the scripts through `env:` only, never through `${{ }}` inside a `run:` block,
so no input is ever interpreted by the shell.

## Crediting contributors

A contribution that came in on GitHub (for example a pull request that was taken over into
COTW on Gitea) reaches GitHub again only as part of the next snapshot. To credit the
contributor there, put them into `co_authors`. GitHub then shows them as co-author of the
snapshot commit.

Format: `Name <email>`, several entries separated by line breaks, `;` or `,`. A pasted
`Co-authored-by:` prefix is accepted. Example:

```text
dawidjasiczek <24965460+dawidjasiczek@users.noreply.github.com>
```

The commit message then becomes

```text
Polish translation

Co-authored-by: dawidjasiczek <24965460+dawidjasiczek@users.noreply.github.com>
```

Rules (checked by [`tools/publish/commit-message.js`](../tools/publish/commit-message.js);
an invalid entry fails the run before anything is pushed, and the error names the entry):

- The name must not be empty and must not contain `,` `;` `<` `>` `"` `\` `` ` `` `$` or control
  characters. Write `Groß, Jürgen` as `Jürgen Groß`.
- The email needs exactly one `@` and a domain with a dot; only letters, digits and `. _ % + -`
  are allowed in the local part.
- Duplicates (same email, any case) are dropped, the first entry wins; an entry with the
  publisher's own address is dropped too.

### Which email to use

GitHub links a co-author by email. Use the address of the contributor's own commits on GitHub,
usually their **noreply address** `<id>+<login>@users.noreply.github.com`:

- Append `.patch` to a commit or pull request URL of the contributor, e.g.
  `https://github.com/Parapoxvirus/cotw/pull/1.patch`; the `From:` line shows name and address.
- Or look up the numeric `id` at `https://api.github.com/users/<login>` and build the address.

### Running it

Always do a dry run first.

**Gitea web UI:** repository → *Actions* → *Publish* → *Run workflow*, branch `main`. Fill in
`tag`, `message` and `co_authors` (the field is single-line, so separate several people with `,`
or `;`), tick `dry_run`, run. The log of the step *Build the snapshot commit* shows the full
commit and the recognized trailers, and ends with `Dry run: nothing pushed to GitHub`. If it
looks right, run again with the same inputs and `dry_run` unticked.

**Gitea API:** with a token that may run workflows (`$GITEA_URL` is the Gitea server, `<owner>`
the owner of the COTW repository there):

```bash
curl -sS -X POST "$GITEA_URL/api/v1/repos/<owner>/cotw/actions/workflows/publish.yml/dispatches" \
  -H "Authorization: token $GITEA_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "ref": "main",
    "inputs": {
      "tag": "v1.2.3",
      "message": "Polish translation",
      "co_authors": "dawidjasiczek <24965460+dawidjasiczek@users.noreply.github.com>",
      "dry_run": "true"
    }
  }'
```

Pass `dry_run` explicitly (`"true"` or `"false"`); any other value fails the run.

### Caveats

- **Same tree, no credit:** when GitHub's `main` already has the published tree, no commit is
  created and the trailers go nowhere; the run shows a warning. Credit the contributor with the
  publish that first contains their change.
- **One snapshot, all credits:** every contributor whose work is in the snapshot belongs into
  the same run. A later publish cannot add trailers to an earlier commit.
- **Manual list:** co-authors are not collected from the internal commits. Their author lines
  and trailers are internal and are not published.
