# One workflow per repository

Every probityai repository runs its pull-request checks from one workflow that ends in an `always()` job named `ci-ok`. The main ruleset requires `ci-ok` alone, with the merge queue and strict freshness. A path-selected `changes` job decides which groups of jobs a change needs, so a docs edit does not start the test matrix, and a new check is a new job in the same file, not a new workflow that starts its own runner for every push.

`scripts/fold-workflows.py` holds the rule in both directions.

- `python3 scripts/fold-workflows.py` folds each workflow that runs on `pull_request` into `.github/workflows/ci.yml` and deletes it. Run it again whenever a repository gains one: the groups already in `ci.yml` stay, and the new ones are added beside them.
- `python3 scripts/fold-workflows.py --check` fails, and names the file, when a second workflow runs on `pull_request`, when the `ci-ok` workflow lacks `merge_group` or `cancel-in-progress`, when `ci-ok` has no `always()`, or when `ci-ok` does not need a job.

A repository runs the check from its own `ci.yml` by pinning the action to a commit:

```yaml
  one-workflow:
    name: One pull-request workflow
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - uses: probityai/.github/actions/workflow-fold@<commit>
```

`ci-ok` must list the job in `needs`, like every other job. Tests: `python3 -m unittest discover -s tests`.
