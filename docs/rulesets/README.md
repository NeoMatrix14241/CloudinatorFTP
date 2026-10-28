# GitHub rulesets for `main` and `dev` (CLAUDE.md 5.32)

Two ready-to-import branch rulesets. They are reference files: GitHub does not read them from the
repository, you import each one once.

| File | Branch | Rules | Who may bypass |
|---|---|---|---|
| `main.json` | `main` (stable) | pull request required (0 approvals), checks `smoke + check` and `behavioral tests` must pass, no force-push, no deletion | repository admins, **only through a pull request** |
| `dev.json` | `dev` (beta) | the same rules | repository admins, always (the emergency exit when a runner is down) |

## Import

1. Repository, **Settings**, **Rules**, **Rulesets**, **New ruleset**, **Import a ruleset**.
2. Choose `dev.json`, check the preview, **Create**. Repeat with `main.json`.
3. If the import is refused, create the ruleset by hand with the same values (the table above).

The check names are the JOB names of `.github/workflows/tests.yml` and must stay exactly
`smoke + check` and `behavioral tests`; renaming a job makes the rule wait for a check that never
reports. A check appears in the picker only after the workflow ran once on the repository.

## Working with them

- Direct pushes to `dev` / `main` are rejected (a required check cannot exist before the push):
  work on a short-lived branch, open a pull request into `dev`, merge when both checks are green.
  `dev` into `main` is the release step.
- `dependency audit` (`.github/workflows/audit.yml`) is deliberately NOT a required check.
- Rulesets and branch protection on a PRIVATE repository need a paid GitHub plan; on a public
  repository they are free.