# Contributing to COTW

Corrections, new languages and code are welcome: open an issue or a pull request on GitHub.
For a name or a capital, cite the official source it comes from and state whether it supports
locale-specific spelling or a shared factual choice. The naming/factual-content policy, source
roles, fallback order and provenance rules for deliberately absent formal names are in
[`docs/TRANSLATING.md`](docs/TRANSLATING.md).

## How a pull request is taken over

The GitHub repository is a **published snapshot** of the main COTW repository, not the place
where development happens. A pull request is therefore not merged on GitHub:

1. The change is applied in the main COTW repository, with the contributor as commit author.
2. The next publication to GitHub contains it and credits the contributor with a
   `Co-authored-by` trailer on the snapshot commit.
3. The GitHub pull request is then closed by hand with a link to the release that contains the
   change. GitHub shows it as *Closed*, not *Merged*; the change is in all the same.

Details of the publication: [`docs/PUBLISHING.md`](docs/PUBLISHING.md).

## Translations

A new language is a BCP 47 locale (`fr-FR`): one module, the names in the data and the locale's
entry in [`data/locales.yaml`](data/locales.yaml), nothing else. The checklist, the naming
sources per language and the rules every language follows:
[`docs/TRANSLATING.md`](docs/TRANSLATING.md). The wanted languages and their sources:
[`data/locales.yaml`](data/locales.yaml).

## Before opening a pull request

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,fetch]"
.venv/bin/python -m cotw validate
.venv/bin/python -m pytest
node --test tests/js/*.test.js
```

## License

COTW is dedicated to the public domain under [CC0 1.0](LICENSE); contributions are published
under the same dedication.
