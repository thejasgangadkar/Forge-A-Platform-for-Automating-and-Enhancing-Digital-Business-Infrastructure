# Generation Performance & Reliability Fixes (2026-10-30)

Session log of the work done after the project had been idle for several weeks.
Everything below was measured on the live stack, not estimated.

## Symptom

A full website build took 8-14 minutes, the server stopped answering other
requests while a build ran, and fetching the generated site immediately after
a build failed with "connection aborted" or timed out.

## Root causes found (all confirmed by measurement)

1. **The model was deliberating for tens of thousands of tokens before writing
   any HTML.** This was the single biggest cost. The page prompt asked the
   model to *decide* things ("derive a palette from the business type",
   "think about the structure"), and a reasoning model responds to that by
   thinking first - 26,000 reasoning tokens, first token at 191 seconds, and in
   the worst runs a whole build that ended with **no HTML at all**.
   *Rewriting the prompt to state every decision as a fact removed the
   deliberation entirely: 0 reasoning tokens, first token in ~1.5 s.*

2. **All four pages were requested in one call**, so the site was one enormous
   ~25K-token response streamed end to end. Splitting it into four concurrent
   per-page calls means the wall-clock time is that of the slowest single page.

3. **Non-streaming requests were used.** A streamed request for the same page
   returned in 39 s where the non-streaming one took 152 s, because a
   non-streaming call waits for the provider to assemble the whole response.

4. **The one-shot token ceiling was too low** (32K for a 45-50K token site), so
   the call was cut off mid-page and the result had to be rebuilt page by page.

5. **The page parser dropped a page** whenever the model formatted its marker
   slightly differently - which triggered a whole extra LLM call.

6. **The blocking build froze the whole event loop.** `generate_endpoint` was
   `async def` but called the entirely synchronous pipeline inside it, so for
   the whole build the server could not answer *any* request.

7. **An aborted connection wedged the listening socket (Windows).** uvicorn's
   Proactor loop raises `OSError [WinError 64]` from `accept()` when a client
   disconnects - which happens every time a browser gives up on the long
   build request - and the server then refused every later connection.

8. **Small token budgets truncated the model's own JSON.** The chat, agent
   config, keyword and assistant calls asked for 150-1100 tokens, but a
   reasoning model spends part of that thinking, so replies were cut off
   mid-sentence and JSON objects were cut off mid-object.

## Changes made

| File | Change |
|---|---|
| `forge.config.env` | `BUILD_MODEL` -> `z-ai/glm-5.3`; `BUILD_MODEL_ALT` -> `deepseek/deepseek-v4-flash` (paid backup on the same provider); `BUILD_STRATEGY=parallel`; `PAGE_MAX_TOKENS=16000`; `WEBSITE_MAX_TOKENS=64000`; `PAGE_CONCURRENCY=4`; run command uses the new loop factory |
| `services/generation_service.py` | Four pages generated as **concurrent per-page calls**; prompt rewritten to be terse and factual (this is what removes the reasoning tax); shared design brief reduced to a fact sheet; tolerant page parser with document-boundary recovery; agent-config budget 700/1100 -> 2000/3000; keyword budget 150 -> 600 |
| `services/llm_service.py` | All completions now **streamed**; explicit 900s provider timeout; bounded retry growth; new `_repair_truncated_json()` |
| `services/chat_service.py` | Chat budget 1100 -> 2500 |
| `services/workspace_assistant.py` | Intent-routing budget 400 -> 1200 |
| `main.py` | All blocking endpoints moved off the event loop with `run_in_threadpool` (`/api/chat`, `/api/generate`, `/agent/chat`, `/assist`, `/edit`) |
| `loop_factory.py` (new) | Windows-safe uvicorn loop factory (Selector loop) |

## Measured results

| | Original | After the fixes |
|---|---|---|
| Chat reply | 27.5 s | **9 s** |
| Full 4-page build | **853 s (14.2 min)** | **112 s (1.9 min)** |
| Page generation itself | - | **39 s** (4 pages in parallel) |
| Reasoning tokens per build | 26,000+ | **0** |
| Builds with a wasted retry | every time | none |
| Server during a build | frozen | fully responsive |
| Server after an aborted request | refused connections | healthy |

The build went from **14.2 minutes to under 2 minutes** - about 7.6x faster -
and the server is now responsive throughout.

## The lesson worth keeping (also why the model choice is not the whole story)

`z-ai/glm-5.3` was rejected earlier in this session because on the *original*
one-shot prompt it returned no HTML at all while burning $0.22 on reasoning.
With the rewritten prompt the same model produces a complete page in 21 s with
zero reasoning. The prompt, not the model, was the deciding factor.

A model that reasons is a liability on a task with no reasoning to do. The fix
is not to avoid reasoning models - it is to give them nothing to deliberate
about, and to keep every prompt factual and short.

