# Spec drift across the family

The family's repositories name each other's identifiers: a predicate type URI in a reader or a README, a corpus id in a workflow's `corpus:` input. Each identifier has one home, the repository that defines it. When the home renames or drops one, or a consumer names one the home never published, neither repository fails on its own.

`.github/workflows/spec-drift.yml` is a reusable workflow that checks the caller out at the commit under test and every other family repository at its default branch, then runs `scripts/spec_drift.py` with the checks in `spec-drift.toml`:

| Check | Home | What must hold |
| --- | --- | --- |
| `predicate-uri-registered` | agent-evidence-vectors | a `probityai.github.io/agent-evidence-vectors/predicate/v<N>/<name>` URI is listed in `spec/predicates/REGISTRY.md` as `predicate/v<N>/<name>` |
| `w3id-predicate-page` | agent-evidence-vectors | a `w3id.org/agent-evidence/predicate/v<N>/<name>` URI has its page under `pages/predicate/v<N>/<name>/` |
| `corpus-id-published` | agent-evidence-vectors | a corpus id passed to the Action or the command line is in `corpora/REGISTRY.toml` |

A type URI is read by its whole path segment, so a name the registry could never hold (`Observed-Effect`, `observed_effect`) is a finding rather than a URI the check does not see; the host is matched without regard to case and the namespace on its own is not a type. Each file is read once; a file over 2 MB or not UTF-8 is not read, and the summary counts and names each one. A finding fails the run in the repository whose file holds it and in the home, where the fix goes. Every other finding is listed in the job summary. Case data, captures, vendored trees and tests are not scanned, because a case that names a wrong identifier on purpose is a test, not drift.

A repository runs it as one job of its batch CI:

```yaml
  spec-drift:
    uses: probityai/.github/.github/workflows/spec-drift.yml@<commit>
```

The checks are read from this repository's `main` branch on purpose, so a new check reaches every caller on its next run.
