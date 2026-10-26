---
base_model: Qwen/Qwen3-0.6B
base_model_revision: c1899de289a04d12100db370d81485cdf75e47ca
library_name: peft
pipeline_tag: text-generation
license: apache-2.0
tags: [lora, sft, transformers, trl]
---

# IntentCart bounded tool controller

Task-specific rank-8 query/value LoRA for the pinned Qwen3-0.6B base. The controller proposes one schema-checked planning tool; it has no payment or account-permission tool. Use the application setup and review controls described in the root README.

Initial training used 915 authored synthetic examples and 360 steps on a free Colab v5e-1 TPU. The current continuation used TRL completion-only SFT, 128 optimizer steps and 512 presentations from a 704-row training partition on local Apple MPS in float32. It trains 1,146,880 adapter parameters. The pinned merged Q8 artifact serves through llama.cpp on CPU.

In the related CPU Q8 policy diagnostic, the continuation matched 105/107 persona/context prompts versus 58/107 for its parent; both matched 59/59 original permission-policy targets. Of the test prompts, 103/107 share an exact observed finite state with training. These are related synthetic policy/format diagnostics, not unseen-state generalization, human usefulness or a general agent benchmark. Two Q8 errors remain. The full journey corpus was not all used to train this adapter.

See the adjacent manifest for exact weights, partitions, hardware, evaluation and overlap audit, and the root README for limitations. Original authored data and reproducible training scripts are under training/. No human feedback, online RL, production safety certification or universal task competence is claimed.

Qwen-derived weights retain the bundled Apache-2.0 license and source notices. The project source license does not replace upstream model licenses.
