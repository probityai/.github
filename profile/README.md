# Probity

**Check what an AI agent did, from the bytes, before you trust it.**

<p align="center"><picture><source media="(min-width: 1012px)" srcset="https://raw.githubusercontent.com/probityai/probityai.github.io/main/figures/f1-four-verdicts/1/wide-auto.svg"><img src="https://raw.githubusercontent.com/probityai/probityai.github.io/main/figures/f1-four-verdicts/1/narrow-auto.svg" alt="A sealed archive of three files travels to a verifier. Intact, it is verified, exit 0. A byte changed on the way breaks the seal: failed, exit 2. A required file lost on the way: not-established, exit 3. A changed verifier: the old and the changed verifier both read the archive and both say verified, exit 0, and both receipts are kept."></picture></p>

For platform, security and audit teams who receive a claim about an agent run and need a decision they can replay offline.

```sh
pip install probityai==0.1.1
samples="$(python -c 'import importlib.resources as r; print(r.files("probity_verify") / "samples")')"
probityai verify "$samples/case.json" --policy "$samples/policy-june.json"
```

```text
Decision: contradicted
Reason: selected_span_missing_from_record
```

<!-- Graded-server sample: one public graded record goes here when the feed opens (operator yes). -->

## Three verbs

| Verb | What it does | Install |
| --- | --- | --- |
| `probityai verify` | decide a claim against pinned evidence or a DSSE envelope | `pip install probityai==0.1.1` |
| `uvx agent-evidence-vectors` | test any verifier against the public conformance corpus | `uvx agent-evidence-vectors==0.31.2` |
| `ratchet` | turn an observed agent failure into a guard proven by replay | `pip install probity-ratchet==0.3.3` |

Explore retained runs or contribute one in the [Open Evidence Lab](https://probityai.github.io/agent-evidence-atlas/lab.html). Browse the task catalog in [HTML](https://probityai.github.io/agent-evidence-atlas/start.html) or [Markdown](https://probityai.github.io/agent-evidence-atlas/start.md). Read the [agent guide](https://probityai.github.io/agent-evidence-atlas/llms.txt) for commands and pinned sources.

## Choose a tool

| Task | Project |
| --- | --- |
| Choose a tool or inspect recorded claims and retained runs | [Agent Evidence Conformance Board](https://github.com/probityai/agent-evidence-vectors/blob/c25bf904877985625655595a905542282e069868/site/README.md) |
| Sign and verify DSSE envelopes in Rust | [dsse](https://github.com/probityai/agent-evidence-vectors/blob/c25bf904877985625655595a905542282e069868/crates/dsse/README.md) |
| Reject duplicate JSON keys and canonicalize in Rust | [jcs-admit](https://github.com/probityai/agent-evidence-vectors/blob/c25bf904877985625655595a905542282e069868/crates/jcs-admit/README.md) |
| Record file actions or check native delegation evidence | [Probity Observer](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/observer/README.md) |
| Test a verifier against conformance cases | [Agent Evidence Vectors](https://github.com/probityai/agent-evidence-vectors/blob/9e596fbff7bb29809d38319aebb56f2141923eb2/README.md) |
| Install a pinned verifier and check an evidence claim | [Probity Verify](https://github.com/probityai/probity/blob/08a27efd567a754ce72a4c789e23f28924f49754/packages/probity-verify/README.md) |
| Use shared definitions for agent evidence claims | [Probity Vocabulary](https://github.com/probityai/agent-evidence-vectors/blob/c25bf904877985625655595a905542282e069868/packages/vocabulary/README.md) |
| Run a checkout composition and replay its retained claims | [Checkout composition reference](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/examples/checkout-runner/README.md) |
| Check artifact digests or evaluate admission policies | [Probity Admission](https://github.com/probityai/agent-evidence-vectors/blob/c25bf904877985625655595a905542282e069868/packages/admission/README.md) |
| Check an agent guard against replay and regression cases | [Probity Ratchet](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/ratchet/README.md) |

## Prove an agent harness change

Ratchet turns each observed agent failure into an executable guard.
It proves the guard by replay against recorded history and fresh held-out runs before admitting it, and signs
every admission decision with the
[agent change admission predicate](https://github.com/probityai/agent-evidence-vectors/blob/main/packages/vocabulary/docs/predicates/agent-change-admission-v1.md).
Install it with `pip install probity-ratchet==0.3.3`; its
[README](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/ratchet/README.md)
gives the commands and the recorded results.

## The standard

Agent Evidence is the open standard; Probity checks and grades against it. [probityai/agent-evidence-vectors](https://github.com/probityai/agent-evidence-vectors) holds the conformance corpus, the vocabulary (`agent-evidence-vocabulary==0.8.0`), admission rules (`agent-evidence-admission==0.2.0`), the `dsse` (0.1.6) and `jcs-admit` (0.1.3) crates, and the conformance board. [probityai/probity](https://github.com/probityai/probity) holds the verifier, the `probityai` command, Ratchet, and two evidence-layer packages: the observer (`agent-evidence-observer==0.1.3`) and the MCP server (`agent-evidence-mcp==0.2.5`). Packages named `agent-evidence-*` are the neutral layer any tool can pin; packages named `probity*` are the checks built on it. Each package keeps its own version and release tag.
