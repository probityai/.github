# Probity

Open source tools for checking AI agent actions. Choose a tool by task.

Explore retained runs or contribute one in the [Open Evidence Lab](https://probityai.github.io/agent-evidence-atlas/lab.html).
Browse the task catalog in [HTML](https://probityai.github.io/agent-evidence-atlas/start.html) or [Markdown](https://probityai.github.io/agent-evidence-atlas/start.md).
Read the [agent guide](https://probityai.github.io/agent-evidence-atlas/llms.txt) for commands and pinned sources.
Use the [replay procedure](https://probityai.github.io/agent-evidence-atlas/replay-tools.html) to run a published example and keep its evidence.

## Choose a tool

| Task | Project |
| --- | --- |
| Evaluate admission policies or reserve cost before dispatch | [Probity Admission](https://github.com/probityai/agent-evidence-admission/blob/bbff435d11a7c0ec9bc0e8e65e6d8fc40c10b671/README.md) |
| Choose a tool or inspect recorded claims and retained runs | [Probity Atlas](https://github.com/probityai/agent-evidence-atlas/blob/48b9648a277bc5177f9dce290551f385c6df2ba1/README.md) |
| Sign and verify DSSE envelopes in Rust | [dsse](https://github.com/probityai/dsse/blob/35e418022b19bebedec13ebb4c31bc43b1c70caf/README.md) |
| Admit and canonicalize JSON in Rust | [jcs-admit](https://github.com/probityai/jcs-admit/blob/fb32a68aa2772e51cee32bc14835075d88af3953/README.md) |
| Record file actions or check native delegation evidence | [Probity Observer](https://github.com/probityai/agent-evidence-observer/blob/753932b42b00ab8257396112c529f840396f0ce7/README.md) |
| Test a verifier against conformance cases | [Probity Vectors](https://github.com/probityai/agent-evidence-vectors/blob/44042ae1a8cbde9444e8ea24e6690a7e773af65b/README.md) |
| Install a pinned verifier and check an evidence claim | [Probity Verify](https://github.com/probityai/probity-verify/blob/437e484bd81e3d1eb1b9ad7230124a434a7a0ef6/README.md) |
| Use shared definitions for agent evidence claims | [Probity Vocabulary](https://github.com/probityai/agent-evidence-vocabulary/blob/4029a7801e0ec61a9818fd1e6c1cbd236e2c82bc/README.md) |

Try a worked task:

- [Issue a local refund with safe retries](https://github.com/probityai/agent-evidence-observer/blob/753932b42b00ab8257396112c529f840396f0ce7/docs/APS-REFUND-RETRIES.md).
- [Check published trace records](https://github.com/probityai/jcs-admit/blob/fb32a68aa2772e51cee32bc14835075d88af3953/interop/mintid-trace-records-v2/README.md).

Each project explains its supported commands and examples in its README.
Verify links to source-pinned installation and checked task recipes. Admission
includes policy-engine rules and a pre-call budget API and CLI for bounded local workloads.
Retained runs keep source revisions, readers, operators and rerun instructions with the result.
