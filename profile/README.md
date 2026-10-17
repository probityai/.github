# Probity

**Evidence about AI agent actions that anyone can check again from the bytes.**

[![agent-evidence-vectors on PyPI](https://img.shields.io/pypi/v/agent-evidence-vectors.svg?label=agent-evidence-vectors)](https://github.com/probityai/agent-evidence-vectors)
[![probity-verify on PyPI](https://img.shields.io/pypi/v/probity-verify.svg?label=probity-verify)](https://github.com/probityai/probity-verify)
[![jcs-admit on crates.io](https://img.shields.io/crates/v/jcs-admit.svg?label=jcs-admit)](https://github.com/probityai/jcs-admit)
[![dsse on crates.io](https://img.shields.io/crates/v/dsse.svg?label=dsse)](https://github.com/probityai/dsse)

![An intact archive verifies, a changed byte fails, a missing artifact is not established, and a changed verifier keeps both outcomes](https://raw.githubusercontent.com/probityai/agent-evidence-vectors/49477c557be579327867ef4d77e73fe220208053/demo/four-arms.gif)

Replay a public conformance corpus through the bundled reference verifier, with nothing to clone. Python 3.11+ and uv are enough:

```bash
uvx agent-evidence-vectors==0.18.0
```

Add `--verifier "<your command>"` to test your own verifier against the same records.

Check any verifier of signed AI-agent and supply-chain records against a public corpus. Choose a tool by task.

Explore retained runs or contribute one in the [Open Evidence Lab](https://probityai.github.io/agent-evidence-atlas/lab.html).
Browse the task catalog in [HTML](https://probityai.github.io/agent-evidence-atlas/start.html) or [Markdown](https://probityai.github.io/agent-evidence-atlas/start.md).
Read the [agent guide](https://probityai.github.io/agent-evidence-atlas/llms.txt) for commands and pinned sources.
Use the [replay procedure](https://probityai.github.io/agent-evidence-atlas/replay-tools.html) to run a published example and keep its evidence.

## Choose a tool

| Task | Project |
| --- | --- |
| Choose a tool or inspect recorded claims and retained runs | [Agent Evidence Conformance Board](https://github.com/probityai/agent-evidence-atlas/blob/ec67f0375e008cb7befc19a31762490b5cbbe520/README.md) |
| Sign and verify DSSE envelopes in Rust | [dsse](https://github.com/probityai/dsse/blob/8549e5e54080b5f8c864f8b3eba8f57af8bd9c51/README.md) |
| Reject duplicate JSON keys and canonicalize in Rust | [jcs-admit](https://github.com/probityai/jcs-admit/blob/0a058d7b676fb452929337c528b893c7f2121062/README.md) |
| Record file actions or check native delegation evidence | [Probity Observer](https://github.com/probityai/agent-evidence-observer/blob/6c251b9fe98946f96a721521a8ca424efd0b3550/README.md) |
| Test a verifier against conformance cases | [Agent Evidence Vectors](https://github.com/probityai/agent-evidence-vectors/blob/9e596fbff7bb29809d38319aebb56f2141923eb2/README.md) |
| Install a pinned verifier and check an evidence claim | [Probity Verify](https://github.com/probityai/probity-verify/blob/db28cc76e5f5aa6932d5122d9c6241ef7adb7fee/README.md) |
| Use shared definitions for agent evidence claims | [Probity Vocabulary](https://github.com/probityai/agent-evidence-vocabulary/blob/59c93ac4529c1e8fdf6e7cdfff7a950740c873f3/README.md) |
| Run a checkout composition and replay its retained claims | [Checkout composition reference](https://github.com/probityai/agent-checkout-runner/blob/297b5b182bb40605b62586eccbf93a9c68a4aee1/README.md) |
| Check artifact digests or evaluate admission policies | [Probity Admission](https://github.com/probityai/agent-evidence-admission/blob/c8f34fe857a969a5a503e0792466b76797d66355/README.md) |
| Check an agent guard against replay and regression cases | [Probity Ratchet](https://github.com/probityai/ratchet/blob/b2800b26ec6cf60fee8e95682660846f674f97c2/README.md) |

## Prove an agent harness change

Ratchet turns each observed agent failure into an executable guard.
It proves the guard by replay against recorded history and fresh held-out runs before admitting it, and signs
every admission decision with the
[agent change admission predicate](https://github.com/probityai/agent-evidence-vocabulary/blob/main/docs/predicates/agent-change-admission-v1.md).
Install it with `pip install probity-ratchet==0.1.0`; its
[README](https://github.com/probityai/ratchet/blob/9736ff12cbf3aff589898b8ae7003cdb13fdf111/README.md)
gives the commands and the recorded results.

## Current releases

Find release states, source revisions and pinned install commands in the [Atlas project catalog](https://probityai.github.io/agent-evidence-atlas/start.html).

Try a worked task:

- [Issue a local refund with safe retries](https://github.com/probityai/agent-evidence-observer/blob/753932b42b00ab8257396112c529f840396f0ce7/docs/APS-REFUND-RETRIES.md).
- [Check published trace records](https://github.com/probityai/jcs-admit/blob/fb32a68aa2772e51cee32bc14835075d88af3953/interop/mintid-trace-records-v2/README.md).

Each project explains its supported commands and examples in its README.
Verify links to source-pinned installation and checked task recipes. Admission
includes policy-engine rules and a pre-call budget API and CLI for bounded local workloads.
Retained runs keep source revisions, readers, operators and rerun instructions with the result.
