---
id: 002
title: Auto-illustrate image fetches — SSRF in judge fetch + safety bait-and-switch
type: security
severity: high
status: fixed
area: open_notebook/graphs/illustrate.py (W2/W3 image pipeline)
created: 2026-07-04
fixed: 2026-07-04
---

# 002 · Auto-illustrate image pipeline — SSRF + safety-judge bait-and-switch

> **✅ FIXED 2026-07-04.** Both findings closed by routing every external image byte-fetch through the
> single guarded, IP-pinned, redirect-revalidating `_ssrf_guarded_fetch`, and by making
> `_fetch_and_store_image` fetch **once** — the safety judge and the stored WebP now derive from the exact
> same bytes. `_fetch_image_data_uri` (relevance + safety judge fetch) now delegates to the guarded fetcher
> and Pillow-decode-gates the bytes before the VLM. Verified: offline SSRF matrix **32/32** against BOTH
> the judge and storage paths (localhost, 169.254.169.254, `::1`, `::ffff:127.0.0.1`, decimal/octal/hex
> IPs, private ranges, non-http scheme, redirect-to-private, redirect-public→public, IP-pin assertion,
> byte caps, Pillow gate, single-fetch assertion, unsafe→abstain) + a **live image e2e** (real chat subject
> → PageImages → guarded relevance judge → single guarded fetch → qwen3.6-VL safety SAFE → WebP 329KB →
> served `200 image/webp`, identical to the pre-fix output — no regression). **W2/W3 are now
> security-clean; only the user's final sign-off remains (end-of-run punch-list).**
>
> Found by the orchestrator's adversarial security review of the W1–W3 diff (chat-foundation),
> 2026-07-04, at commit `5edf9f1`. This is the **W2/W3 security follow-up** the S-gate review was for.
> The **storage fetch itself is clean** (verified) — the gaps were in the *other* fetch and the fetch split.
> **Both findings collapsed into one fix.** The diagram path (W1) was unaffected throughout.

## Finding 1 — HIGH · SSRF not prevented for the judge / relevance / safety fetches
`_fetch_image_data_uri` (illustrate.py:666) fetches bytes for BOTH the W2 relevance judge
(`_judge_candidate` :709) and the W3 safety pre-fetch (`_fetch_and_store_image` :994) with
`follow_redirects=True`, no IP pinning, no per-hop revalidation, and — for the relevance judge — no
SSRF pre-check at all. Three bypasses, all reaching internal hosts with a blind GET from the worker:
1. **Relevance judge (W2) has zero SSRF validation** — every search candidate URL (up to top-K=3) is
   fetched before any winner/validation. `_validate_public_url` only runs later in W3.
2. **Redirect SSRF (W2 + W3)** — W3's pre-check validates only the original URL, then follows redirects
   with no re-validation: public origin → `302 Location: http://127.0.0.1:8000/` is followed.
3. **DNS-rebind TOCTOU** — pre-check `getaddrinfo` and httpx's own resolution are separate lookups; the
   validated IP is discarded (not pinned), so low-TTL rebinding flips the host between check and fetch.

Impact (self-hosted worker): blind GET SSRF to localhost (API :5055, SurrealDB :8000, Ollama :11434/:11435),
cloud metadata (169.254.169.254) on cloud deploys, internal port probing by timing. Attacker vector:
poison a Wikimedia/Openverse search result URL, or prompt-inject the chat to steer candidate subjects.

## Finding 2 — MED-HIGH · Safety judge bypassable by bait-and-switch (judged bytes ≠ stored bytes)
`_fetch_and_store_image` fetches twice independently: `judge_uri = _fetch_image_data_uri(url)` (:994, →
fail-closed safety VLM) and `raw = _ssrf_guarded_fetch(url)` (:1011, → the bytes actually re-encoded,
stored under `CHAT_MEDIA_FOLDER`, served unauth at `GET /api/chat/media/{hash}.webp`). The stored bytes
are never re-judged. A stateful/redirecting origin serves safe bytes to request #1 and unsafe/different
bytes to request #2 → the D3 fail-closed judge gates on content that is not what gets served.

## The fix (both findings, together)
Route **every** image byte-fetch (relevance judge, safety judge, storage) through the single guarded,
IP-pinned, redirect-revalidating `_ssrf_guarded_fetch`, returning bytes **once**; the safety judge and the
WebP re-encode then operate on those exact bytes. Concretely: fetch-guarded once → Pillow-gate → safety
VLM on those bytes → WebP encode + store the same bytes. Delete `_fetch_image_data_uri`'s unguarded path
(or make it delegate to the guarded fetcher). This removes the second fetch entirely (kills Finding 2) and
puts the judge fetch behind the guard (kills Finding 1). Add a Pillow decode gate before the VLM on the
judge bytes too (decompression-bomb defense).

## Lower-severity notes (from the review, defense-in-depth)
- LOW-MED — `media["label"]` derives from the attacker-influenced search-result `title` and flows to the
  chat frontend. React default-escapes, so safe *unless* rendered via `dangerouslySetInnerHTML` — confirm.
- LOW — `_sanitize_mermaid` (:299) is minimal (strips `click`/`<script`/`javascript:`); acceptable given
  client-side DOMPurify + strict render (F4), but model-generated diagram source is injection-steerable.
- INFO — `_ip_is_blocked` (:170) reverses `ipv4_mapped` only; 6to4/Teredo/NAT64 embedded IPv4 not
  range-checked (only relevant if such transition infra exists). CGNAT `100.64.0.0/10` depends on Py version.
- INFO — `GET /api/chat/media/{file}` unauthenticated (accepted decision Q-mediaauth, single-user local).

## Verify after fix
Re-run the review's SSRF matrix (127.0.0.1, 169.254.169.254, localhost, redirect-to-private, DNS-rebind,
::ffff:127.0.0.1, decimal/octal IPs, byte-cap, non-image) against BOTH the judge and storage paths → all
rejected; and confirm a single fetch feeds both judge and store (add a counter/assert). Then re-run the
live image e2e (real chat turn → served .webp) — it PASSED pre-fix (commit 5edf9f1), must still pass.
