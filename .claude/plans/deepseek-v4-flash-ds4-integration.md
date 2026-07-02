# Plan: DeepSeek V4 Flash + DwarfStar (ds4) local-inference integration

**Status:** Research / design — NOT ready to build. Several open questions need answers first (see end).
**Last updated:** 2026-06-22
**Owner context:** Single user. Dev machine = MacBook (48 GB). Inference host = remote DGX Spark
(GB10, 128 GB unified, aarch64 Linux) running the Open Notebook stack + Ollama. User has out-of-band
(IPMI/BMC/remote-KVM or on-site) access to the Spark, so a hung box is reboot-recoverable.

---

## Goal

Use **DeepSeek V4 Flash** (frontier 284B/13B-active MoE, 1M context) inside Open Notebook, run **locally**
on the Spark via **DwarfStar / ds4** (antirez's pure-C inference engine), alongside the existing local
**Qwen 3.6 Flash** (35B/3B) — without crashing the remote box and within the single-stream + memory limits.

---

## TL;DR / current recommendation

- **Integration is zero-code.** ds4 exposes an OpenAI-compatible server; it plugs into the existing
  `openai_compatible` provider. Cloud DeepSeek V4 Flash plugs into the existing `deepseek` / `openrouter`
  providers. No changes to `open_notebook/ai/` needed.
- **Architecture:** Spark = inference server, MacBook = app/cockpit. **Do NOT distribute** across Mac+Spark
  (mixed Metal+CUDA unproven; the Spark fits the model solo anyway; pipeline-parallel only helps *fit*, not speed).
- **Memory is the real constraint, not the integration.** Q2 Flash is **~81 GB** (corrected — see below).
  You **cannot** keep ds4 + Qwen-Q8 resident at once on 128 GB.
- **Two viable designs** (pick one — open question): **A** both-hot with Qwen at **Q4** + a cross-process
  busy-guard; **B** model selection drives engine load/unload so only one big model is resident (Qwen stays Q8).
  Current lean: **Option B** (safer for a remote, risk-averse, manual-selection workflow).
- **Safest path overall** if cloud is acceptable: keep Qwen-Q8 local for the fast lane, use **cloud** V4 Flash
  for the heavy lane → sidesteps the entire 81 GB co-residency problem.

---

## Background: what the two things are

- **DeepSeek V4 Flash** — cloud-released model (2026-04-24). 284B total / 13B active MoE, **1M context**,
  MIT open weights. Native API + OpenRouter, OpenAI- & Anthropic-compatible. Cloud price ~$0.14/$0.28 per 1M
  (OpenRouter lists ~$0.09/$0.18). ⚠️ `deepseek-chat`/`deepseek-reasoner` retire **2026-07-24** — migrate old records.
- **DwarfStar / ds4** — antirez's local inference *engine* (not a model), `github.com/antirez/ds4`. Pure C +
  Metal/CUDA/ROCm. Purpose-built for V4 Flash/PRO. CUDA backend targets the **DGX Spark GB10** specifically.
  Ships `ds4-server` (OpenAI `/v1/chat/completions`, Anthropic `/v1/messages`) + `ds4` CLI. **Beta** ("exists
  only a few days" per README) — verify flags on the installed build.

---

## Grounded findings — Open Notebook codebase (verified 2026-06-22)

**Model/provider plumbing (no code changes needed to add models/providers):**
- Providers are config, not code: `PROVIDER_CONFIG` in `open_notebook/ai/key_provider.py:28-73` already lists
  `deepseek`, `ollama`, etc.; `openai_compatible` handled by `_provision_openai_compatible()`
  (`key_provider.py:221-243`) and normalized `openai_compatible`→`openai-compatible` for Esperanto.
- Credential → Esperanto config passes `base_url` straight through: `credential.to_esperanto_config()`
  (`open_notebook/domain/credential.py:102-137`). ds4 just needs a `base_url` credential.
- Model records are plain rows: name/provider/type/credential (`open_notebook/ai/models.py`). Adding
  `deepseek-v4-flash` is a row, not a migration.
- Esperanto pinned `>=2.20.0,<3` (pyproject). Discovery defaults unknown model names to `language` → fine.

**Role routing already exists (this is the lever for "use the right model per task"):**
- `provision_langchain_model()` auto-upgrades to `large_context_model` when `tokens > 105_000`
  (`open_notebook/ai/provision.py:23-28`). Hard-coded threshold.
- `DefaultModels` slots: `default_chat_model`, `default_transformation_model`, `default_tools_model`,
  `large_context_model`, `default_embedding_model`, `default_text_to_speech_model`,
  `default_speech_to_text_model` (`open_notebook/ai/models.py`).
- Per-request override: `ChatSession.model_override` + `model_id` config in chat graph
  (`open_notebook/graphs/chat.py:59-60`, `api/routers/chat.py:358`).

**Queuing / concurrency — partial (verdict: queue exists, model-call gating does NOT):**
- Real async job queue = **surreal-commands**. Background jobs registered in `commands/`:
  `embed_note/embed_source/embed_insight` (`commands/embedding_commands.py`), `process_source` +
  `run_transformation` (`commands/source_commands.py`), `generate_podcast` (`commands/podcast_commands.py`).
  Submitted via `api/command_service.py:11-40`. Worker started by `surreal-commands-worker --import-modules
  commands` (`Makefile:143-145`).
- **No worker concurrency config** anywhere (no `WORKER_CONCURRENCY`/pool setting).
- **Chat / Ask / Transformation-execute are SYNCHRONOUS** in the HTTP request, NOT queued
  (`api/routers/chat.py:382`, `api/routers/search.py`, `api/routers/transformations.py:81`).
- **No semaphore/lock/rate-limit** around any model call. Concurrent requests hit the model concurrently.
- ⚠️ API and the surreal-commands worker are **separate processes** → any cross-process "model busy" guard
  must be shared state (e.g., a SurrealDB lock row), not an in-process asyncio lock.

---

## Grounded findings — ds4 / hardware reality (verified 2026-06-22)

**Memory (CORRECTION to an earlier under-estimate):**
- Q2 Flash GGUF = **~81 GiB** (not ~40 GB). + KV cache **up to ~26 GB** at max context.
  (Asymmetric quant: routed MoE experts IQ2_XXS/Q2_K, dense/shared/projection/routing left at Q8 → resists
  2-bit very well.) Sources: ds4 README; `github.com/Entrpi/ds4-on-spark`.
- Q4 Flash needs 256 GB+ — **not** an option on a 128 GB Spark.
- **Co-residency math on 128 GB (~120 GB usable):**
  - ds4 Q2 (81) + Qwen Q8 (35) = 116 weights + KV + ~12 OS/DB/API ≈ **~136 → OOM ❌**
  - ds4 Q2 (81) + Qwen **Q4** (~19) + disk-KV + ~12 ≈ **~116 → fits, tight ⚠️**
  - ds4 Q2 (81) alone + KV + ~12 ≈ **~101 → comfortable ✅**
- **ds4-server holds its full 81 GB the whole time it runs** — a call-level lock does NOT reclaim it.
  Freeing it requires stopping ds4-server (cold reload ~20 s).
- Ollama unloads idle models after keep-alive (~5 min default); peak co-residency is only during *overlap*.

**Performance (Spark GB10, single node, in-RAM):**
- Decode ~13–19 t/s (tapers to ~13 at 96k ctx); prefill ~310–460 t/s; ~94–95% of bandwidth roofline.
- Cold start: ~20 s model load, ~21 s TTFT.
- Qwen 3.6 Flash (3B active) is ~5–10× faster (~90–170 t/s) — the reason to keep it as the fast lane.

**Concurrency — ds4 is strictly single-stream:**
- Inference serialized through one graph worker; concurrent requests **queue**, no batching
  (`Entrpi/ds4-on-spark` concurrency analysis; `--concurrency 2` → strictly sequential). Safe (no corruption),
  just blocking. This is the hard "no multi-agentic local work" limit.

**Resource contention verdict (why the webserver/Claude survive):**
- LLM decode saturates **memory bandwidth**; the webserver (FastAPI/SurrealDB) and "talking to Claude"
  (remote cloud inference — local cost is just TCP/TLS) are **I/O-light**, not bandwidth-bound → they keep
  working, maybe small latency bump. Real risk is **capacity → OOM**, controlled by a hard memory cap.

**Distributed inference — investigated, rejected for this setup:**
- ds4 distributed = **pipeline parallelism over TCP** (each node loads only its layer slice; combined RAM =
  what fits). Launch via `--role coordinator/worker --layers a:b`. Network latency dominates decode:
  Thunderbolt 5 ~25 t/s vs WiFi ~10.7 t/s. **Only speeds prefill, not decode.**
- Rejected because: (1) mixing Metal (Mac) + CUDA (Spark) is undocumented/unproven; (2) the Spark fits the
  model solo, so distributing would only *slow* decode; (3) a lone 48 GB Mac can't distribute by itself.

---

## Architecture decision

```
MacBook (48 GB) — cockpit            DGX Spark (128 GB) — muscle
  Open Notebook frontend :3000   LAN   ds4-server (CUDA)  :8080   ← NOTE: not :8000 (DB)
  Open Notebook API     :5055   ───▶   Ollama (Qwen 3.6)
  Claude Code (remote infer)           SurrealDB :8000, worker
  → openai_compatible cred → http://<spark-ip>:8080/v1
```
- ds4 only serves the **language** model; embeddings stay on `qwen3-embedding` via Ollama.
- ⚠️ **Port:** the Spark install script defaults ds4-server to **:8000**, which collides with SurrealDB.
  Use **`--port 8080`** (3000/5055/8000 are taken; 8080 free).

---

## Model role routing strategy (target once both models are available)

| Slot | Model | Rationale |
|---|---|---|
| `default_chat_model` | Qwen 3.6 Flash | snappy interactive |
| `default_transformation_model` | Qwen 3.6 Flash | batch over many sources; speed matters |
| `default_tools_model` | DeepSeek V4 Flash | agentic / tool-use (V4 clearly stronger) |
| `large_context_model` | DeepSeek V4 Flash | auto-engages >105k tokens; 1M context is the point |
| `default_embedding_model` | qwen3-embedding | unchanged |

**Quality note (Q2 vs Q8):** V4 Flash @ Q2 beats Qwen 3.6 Flash @ Q8 on coding/agentic/long-context
(base-model gap > Q2 penalty; asymmetric quant + MoE tolerance keep Q2 near-frontier). ~Tie on plain
MMLU-Pro knowledge MCQ. Qwen wins on **speed** (~5–10×) and **multimodality**.

**Key efficiency pattern:** *summarize-once-chat-cheap* — V4 does the expensive one-time long-context read
→ dense insights/notes; Qwen then chats over the compact distillations fast. Open Notebook's insights/notes
model already supports this; it minimizes how often V4 (single-stream, slow) is invoked.

**Queuing strategy:** route heavy V4 work through the **async job queue** (not the synchronous chat path, which
has no timeout); set worker concurrency = 1; the Qwen(Ollama)/V4(ds4) split already gives two independent
single-stream lanes that only contend on the shared memory bus.

---

## The two candidate designs (DECISION NEEDED)

**Option A — both hot, Qwen Q4 + cross-process busy-guard.**
- ds4-server always up (81 GB) + Qwen Q4 (~19 GB) + disk-KV ≈ 112 GB (fits, tight).
- Add a SurrealDB-backed "model busy" lock so a background job can't spike memory/bandwidth during interactive use.
- Pros: instant switching, true concurrency (fast chat *while* a big ds4 job runs). Cons: Qwen→Q4 quality dip,
  thin margins, new cross-process guard code, must trust the guard on a remote box.

**Option B — selection drives engine load/unload (current lean).**
- Choosing a model manages the engine: ds4 selected → evict Qwen (Ollama `keep_alive=0`) → use ds4; Qwen
  selected → **stop ds4-server** (free 81 GB) → Qwen at full Q8.
- Pros: only ever one big model resident → 81+35 collision impossible by construction; Qwen stays Q8; ~no app code.
  Cons: ~20 s reload on engine switch; not simultaneous.

**Option C — cloud heavy lane.** Qwen-Q8 local fast lane + **cloud** V4 Flash heavy lane. No co-residency
problem at all. Best if offline/privacy/cost don't forbid cloud. (Cheapest in engineering risk.)

---

## Safe install runbook (Spark, guardrails baked in) — for when we proceed

Phase 0 pre-flight: `free -g`; `df -h ~` (need ≥110 GiB); `ss -tlnp | grep -E ':8000|:8080'` (8080 free);
`nvidia-smi --query-gpu=compute_cap --format=csv` (expect 12.1); work inside `tmux`.
Phase 1 protect lifeline: `sudo choom -n -1000 -p $(pgrep -x sshd)`.
Phase 2 build: `git clone https://github.com/antirez/ds4.git && cd ds4 && make cuda-spark` (needs CUDA
toolkit 13.x / nvcc; `make -j20 CUDA_ARCH=sm_121` per Spark repo — explicit arch ~25% faster prefill).
Phase 3 model (~81 GB): `./download_model.sh q2-imatrix` (→ `./ds4flash.gguf`; from
`huggingface.co/antirez/deepseek-v4-gguf`). Optional MTP draft (~3.6 GB) for speculative decode.
Phase 4 isolation test: `./ds4 -p "Say hello." --nothink --ctx 8192` — proceed only if it generates.
Phase 5 **run under hard memory cap (the key safety net):**
```bash
systemd-run --scope -p MemoryMax=100G -p MemorySwapMax=0 \
  ./ds4-server --chdir $PWD --port 8080 --host 0.0.0.0 \
    --ctx 64000 --kv-disk-dir /tmp/ds4-kv --kv-disk-space-mb 16384
```
(MemoryMax → kernel kills ds4-only, never DB/API/SSH; SwapMax=0 → clean death not thrash; disk-KV → predictable RAM.)
Phase 6 verify: `curl localhost:8080/v1/models`; a tiny `/v1/chat/completions` POST.
Phase 7 wire Open Notebook (reversible): `openai_compatible` credential → `http://localhost:8080/v1`; register
`deepseek-v4-flash` language model; keep Qwen as default; assign roles per table above.
Skip the `curl … install.sh | bash` one-liner — use gated manual steps so nothing runs unattended.

---

## Open questions — FURTHER RESEARCH NEEDED (iterate here)

1. **Design decision A vs B vs C** — not yet chosen. Drives everything below. (My lean = B.)
2. **Qwen 3.6 Flash exact memory footprint by quant on the Spark** — confirm real Q4/Q5/Q8 sizes + Ollama
   overhead + its KV at the context size used. The "Q4 ≈ 19 GB" is an estimate. Verify before Option A.
3. **Does the Spark have the full CUDA toolkit / nvcc**, or only the runtime/driver (Ollama needs only the
   driver)? If toolkit missing, installing it risks driver mismatch — research a safe install (or build in a
   CUDA container with `--gpus`/`--memory` for isolation). UNVERIFIED.
4. **ds4-server flag names on the actual installed build** (beta, fast-moving). Confirm `--port/--host/--ctx/
   --kv-disk-dir/--chdir/--power` via `./ds4-server --help` before trusting the runbook.
5. **Engine load/unload mechanics for Option B** — how to cleanly stop/start ds4-server from the app or a
   script, how to set Ollama `keep_alive=0` / force-unload, and where model selection should trigger the swap
   (API layer? a small supervisor script? frontend selector → API → systemd?). Needs design.
6. **Cross-process busy-guard (Option A)** — design the SurrealDB lock row (schema, acquire/release, stale-lock
   timeout, who waits vs errors). Decide if it's also a worthwhile backstop under Option B.
7. **Fallback wiring** — if ds4 is down/loading, V4 roles should fall back (to Qwen or cloud V4) so workflows
   don't hard-fail. Confirm the existing "model fallback" behavior and how to configure it per-role.
8. **Cloud V4 Flash exact native model slug** (vs OpenRouter `deepseek/deepseek-v4-flash`) and the
   post-2026-07-24 naming — confirm for Option C / fallback.
9. **MTP / speculative decode** — does the draft model meaningfully raise decode t/s on the Spark, and what
   extra RAM does it cost? Affects the memory budget.
10. **ds4 reliability under sustained Open Notebook load** — it's beta; soak-test before relying on it for
    background jobs. Define a smoke/soak test.
11. **`make cuda-spark` vs `make -j20 CUDA_ARCH=sm_121`** — reconcile the two documented build invocations;
    confirm which yields the sm_121 native build.

---

## Sources
- ds4 repo + README: https://github.com/antirez/ds4 (README: /blob/main/README.md)
- ds4 on DGX Spark (install/benchmarks/concurrency): https://github.com/Entrpi/ds4-on-spark
- antirez distributed-inference post: https://antirez.com/news/167
- DeepSeek V4 Flash on OpenRouter: https://openrouter.ai/deepseek/deepseek-v4-flash
- DeepSeek V4 docs (release/migration): https://api-docs.deepseek.com/news/news260424
- VRAM/quant tables: https://codersera.com/blog/deepseek-v4-vram-gpu-requirements-2026/ ;
  https://knightli.com/en/2026/05/01/deepseek-v4-local-vram-quantization-table/
- V4 Flash vs Qwen 3.6 Flash: https://codingfleet.com/blog/deepseek-v4-flash-vs-qwen-3-6-flash/
- antirez 2-bit quant detail: https://x.com/antirez/status/2048885632869523869
- GGUF weights: https://huggingface.co/antirez/deepseek-v4-gguf