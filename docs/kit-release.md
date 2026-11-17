# Kit release: build, checksum, attest, publish, verify

`.github/workflows/kit-release.yml` is the release path every family Python distribution shares (the vectors corpus, the vocabulary, admission, the verifier):

1. Build the wheel and the source distribution from the tagged commit, twice; the second build must reproduce the first byte for byte. Check them with `twine check --strict`, write `SHA256SUMS`, and install the wheel alone outside the checkout.
2. Attest every file and `SHA256SUMS` with build provenance.
3. Verify every attestation, and require that a copy with one byte appended is refused.
4. With `release-tag`, upload the files to that GitHub release, download what the release serves, check it against `SHA256SUMS` and verify each attestation again.

It never uploads to a package index: PyPI trusted publishing does not accept a reusable workflow, so the caller's publish job uploads the `kit-<distribution>` artifact this workflow leaves. `.github/workflows/kit-index-verify.yml` then proves the index serves exactly the files `SHA256SUMS` lists, each with its digest.

```yaml
  kit:
    uses: probityai/.github/.github/workflows/kit-release.yml@<commit>
    permissions: {contents: write, id-token: write, attestations: write}
    with: {directory: packages/vocabulary, distribution: agent-evidence-vocabulary,
           version: 1.2.3, release-tag: agent-evidence-vocabulary-v1.2.3}
  publish:
    needs: kit
    # download kit-agent-evidence-vocabulary, upload dist/ with trusted publishing
  index:
    needs: [kit, publish]
    uses: probityai/.github/.github/workflows/kit-index-verify.yml@<commit>
    with: {distribution: agent-evidence-vocabulary, version: 1.2.3}
```

Every attestation names `probityai/.github/.github/workflows/kit-release.yml` as its signer workflow, so a consumer verifies a downloaded file with:

```sh
gh attestation verify <file> --repo <owner>/<repo> --signer-workflow probityai/.github/.github/workflows/kit-release.yml
```
