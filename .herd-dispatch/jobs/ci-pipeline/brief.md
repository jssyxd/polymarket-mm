# ci-pipeline

Deliverable: `.github/workflows/ci.yml` and `.github/workflows/paper.yml`.

ci.yml: on push and pull_request, python 3.11, install the package, run `python -m pytest -q`
and a syntax/lint pass. paper.yml: `workflow_dispatch` with a duration input, runs the paper
pipeline against a checked-in fixture and uploads the ledger as an artifact.

Constraints: no secrets in workflows, no live trading step, caches pip. Prove the YAML parses
(e.g. with a local action linter or PyYAML) and report how.
