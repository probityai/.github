# Probity

**Check what an AI agent did, from the bytes, before you trust it.**

For platform, security and audit teams who receive a claim about an agent run and need a decision they can replay offline.

```sh
pip install probityai==0.1.0
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
| `probityai verify` | decide a claim against pinned evidence or a DSSE envelope | `pip install probityai==0.1.0` |
| `uvx agent-evidence-vectors` | test any verifier against the public conformance corpus | `uvx agent-evidence-vectors==0.29.2` |
| `ratchet` | turn an observed agent failure into a guard proven by replay | `pip install probity-ratchet==0.2.1` |

Explore retained runs or contribute one in the [Open Evidence Lab](https://probityai.github.io/agent-evidence-atlas/lab.html). Browse the task catalog in [HTML](https://probityai.github.io/agent-evidence-atlas/start.html) or [Markdown](https://probityai.github.io/agent-evidence-atlas/start.md). Read the [agent guide](https://probityai.github.io/agent-evidence-atlas/llms.txt) for commands and pinned sources.

## Choose a tool

| Task | Project |
| --- | --- |
| Choose a tool or inspect recorded claims and retained runs | [Agent Evidence Conformance Board](https://github.com/probityai/agent-evidence/blob/44066a188c1b080b7c9bd5a73f6626c229baaa14/site/README.md) |
| Sign and verify DSSE envelopes in Rust | [dsse](https://github.com/probityai/agent-evidence/blob/44066a188c1b080b7c9bd5a73f6626c229baaa14/crates/dsse/README.md) |
| Reject duplicate JSON keys and canonicalize in Rust | [jcs-admit](https://github.com/probityai/agent-evidence/blob/44066a188c1b080b7c9bd5a73f6626c229baaa14/crates/jcs-admit/README.md) |
| Record file actions or check native delegation evidence | [Probity Observer](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/observer/README.md) |
| Test a verifier against conformance cases | [Agent Evidence Vectors](https://github.com/probityai/agent-evidence-vectors/blob/9e596fbff7bb29809d38319aebb56f2141923eb2/README.md) |
| Install a pinned verifier and check an evidence claim | [Probity Verify](https://github.com/probityai/probity-verify/blob/db28cc76e5f5aa6932d5122d9c6241ef7adb7fee/README.md) |
| Use shared definitions for agent evidence claims | [Probity Vocabulary](https://github.com/probityai/agent-evidence/blob/44066a188c1b080b7c9bd5a73f6626c229baaa14/packages/vocabulary/README.md) |
| Run a checkout composition and replay its retained claims | [Checkout composition reference](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/examples/checkout-runner/README.md) |
| Check artifact digests or evaluate admission policies | [Probity Admission](https://github.com/probityai/agent-evidence/blob/44066a188c1b080b7c9bd5a73f6626c229baaa14/packages/admission/README.md) |
| Check an agent guard against replay and regression cases | [Probity Ratchet](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/ratchet/README.md) |

## Prove an agent harness change

Ratchet turns each observed agent failure into an executable guard.
It proves the guard by replay against recorded history and fresh held-out runs before admitting it, and signs
every admission decision with the
[agent change admission predicate](https://github.com/probityai/agent-evidence/blob/main/packages/vocabulary/docs/predicates/agent-change-admission-v1.md).
Install it with `pip install probity-ratchet==0.2.1`; its
[README](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/ratchet/README.md)
gives the commands and the recorded results.

## The standard

Agent Evidence is the open standard; Probity checks and grades against it. [probityai/agent-evidence](https://github.com/probityai/agent-evidence) holds the vocabulary (`agent-evidence-vocabulary==0.8.0`), admission rules (`agent-evidence-admission==0.2.0`), the `dsse` (0.1.5) and `jcs-admit` (0.1.3) crates, and the conformance board. [probityai/probity](https://github.com/probityai/probity) holds the verifier, the observer (`agent-evidence-observer==0.1.1`) and Ratchet.
