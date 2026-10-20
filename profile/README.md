# Probity

**Evidence about AI agent actions that anyone can check again from the bytes.**

[![agent-evidence-vectors on PyPI](https://img.shields.io/pypi/v/agent-evidence-vectors.svg?label=agent-evidence-vectors)](https://github.com/probityai/agent-evidence-vectors)
[![probity-verify on PyPI](https://img.shields.io/pypi/v/probity-verify.svg?label=probity-verify)](https://github.com/probityai/probity-verify)
[![jcs-admit on crates.io](https://img.shields.io/crates/v/jcs-admit.svg?label=jcs-admit)](https://github.com/probityai/agent-evidence/tree/main/crates/jcs-admit)
[![dsse on crates.io](https://img.shields.io/crates/v/dsse.svg?label=dsse)](https://github.com/probityai/agent-evidence/tree/main/crates/dsse)

![An intact archive verifies, a changed byte fails, a missing artifact is not established, and a changed verifier keeps both outcomes](https://raw.githubusercontent.com/probityai/agent-evidence-vectors/49477c557be579327867ef4d77e73fe220208053/demo/four-arms.gif)

Replay a public conformance corpus through the bundled reference verifier, with nothing to clone. Python 3.11+ and uv are enough:

```bash
uvx agent-evidence-vectors==0.20.0
```

Add `--verifier "<your command>"` to test your own verifier against the same records.

Check any verifier of signed AI-agent and supply-chain records against a public corpus. Choose a tool by task.

Explore retained runs or contribute one in the [Open Evidence Lab](https://probityai.github.io/agent-evidence-atlas/lab.html).
Browse the task catalog in [HTML](https://probityai.github.io/agent-evidence-atlas/start.html) or [Markdown](https://probityai.github.io/agent-evidence-atlas/start.md).
Read the [agent guide](https://probityai.github.io/agent-evidence-atlas/llms.txt) for commands and pinned sources.
Use the [replay procedure](https://probityai.github.io/agent-evidence-atlas/replay-tools.html) to run a published example and keep its evidence.

## Start here

- [Agent Evidence](https://github.com/probityai/agent-evidence): the open standard, with conformance vectors, a vocabulary, admission rules and the `dsse` and `jcs-admit` crates.
- [Probity](https://github.com/probityai/probity): the verifier and the `probity` command.

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
Install it with `pip install probity-ratchet==0.1.2`; its
[README](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/ratchet/README.md)
gives the commands and the recorded results.

## Current releases

Find release states, source revisions and pinned install commands in the [Atlas project catalog](https://probityai.github.io/agent-evidence-atlas/start.html).

Try a worked task:

- [Issue a local refund with safe retries](https://github.com/probityai/probity/blob/e2164379c19cf17a00356dfbdf625a998272ac58/packages/observer/docs/APS-REFUND-RETRIES.md).
- [Check published trace records](https://github.com/probityai/agent-evidence/blob/44066a188c1b080b7c9bd5a73f6626c229baaa14/crates/jcs-admit/interop/mintid-trace-records-v2/README.md).

Each project explains its supported commands and examples in its README.
Verify links to source-pinned installation and checked task recipes. Admission
includes policy-engine rules and a pre-call budget API and CLI for bounded local workloads.
Retained runs keep source revisions, readers, operators and rerun instructions with the result.
