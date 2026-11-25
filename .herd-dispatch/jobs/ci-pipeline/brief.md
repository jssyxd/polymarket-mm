# ci-pipeline

Deliverable: `.github/workflows/ci.yml` and `.github/workflows/paper.yml`.

ci.yml: on push and pull_request, python 3.11, install the package, run `python -m pytest -q`
and a syntax/lint pass. paper.yml: `workflow_dispatch` with a duration input, runs the paper
pipeline against a checked-in fixture and uploads the ledger as an artifact.

Constraints: no secrets in workflows, no live trading step, caches pip. Prove the YAML parses
(e.g. with a local action linter or PyYAML) and report how.

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM/polymarket-mm/.herd-dispatch/worktrees/ci-pipeline
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
