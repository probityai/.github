# How the public repositories keep their version pins current

Every public probityai repository names versions of the family packages it installs: a lock in `version-pins.toml`, the pages the lock holds and, in the tap, the Homebrew formulas. A release of one package used to leave the others naming the release before it until someone moved them by hand.

## The mechanism

`actions/pin-refresh` runs in each consuming repository. It moves each family lock to the newest release, rewrites the pages the lock holds, puts back any change under `.github/workflows` (Dependabot owns the Action pins there), commits on a branch named after the change, opens a pull request, runs the repository's own CI on that branch and merges when every run succeeded. A failed run leaves the pull request open with the failing run named.

Dependabot keeps manifests (`pyproject.toml`, `uv.lock`, `Cargo.toml`) and the Action pins in workflow files. History never moves: `[scan] historical`, `version-pins: keep` and `off` to `on` are read by the rewrite exactly as by the check.

## Decisions

- **No cross-repository release dispatch.** A token made by Actions cannot dispatch a workflow in another repository, and the only alternatives are a GitHub App or an organisation secret, which this needs neither of. Each consuming repository polls hourly instead, so a release reaches it within an hour. The check that fails closed (`registry-verify`) lets a lock lag by one release for one day, so the poll sits well inside it. A release in the same repository starts the refresh at once through `workflow_run`.
- **A bump pull request opened by `GITHUB_TOKEN` gets no `pull_request` run.** The action dispatches the repository's CI workflows on the bump branch (`workflow_dispatch`) and merges with `--match-head-commit` when they all succeeded. A repository whose branch rules require checks that exist only on `pull_request` events (vectors: `dco/sign-off`, governance, no-internal-drafts, identity-scan) cannot merge by itself until those workflows accept `workflow_dispatch`; its refresh opens the pull request and leaves the merge to a person.
- **Homebrew settles a release for a day.** `brew update-python-resources` refuses a package uploaded within the last day. A config that feeds a tap sets `[refresh] settle_hours = 25`: the lock moves only to a release at least that old, and the one-day grace grows by the same hours.
- **Brew-provided packages are not resources.** A formula that lists `depends_on "cryptography"` gets `--exclude-packages=cryptography`, so the resource blocks hold only what brew does not provide.
