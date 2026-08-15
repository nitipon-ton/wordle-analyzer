# Wordle Toolkit — Engineering Analysis

Analysis of the solver bot (`api/next_word.py`), the opening analyzer (`api/analyze.py`), and the
frontend (`public/index.html`). Covers correctness, performance, and solver quality, with
measured benchmarks and prototyped alternatives.

Measured on: Python 3.14.6, Windows 11, 688-word answer list / 14,855-word guess list.

---

## TL;DR

| Area | Verdict |
|---|---|
| Wordle pattern logic | **Correct.** 0 mismatches vs an independent reference over 200,000 random pairs |
| Solver quality | **Very strong.** 3.07 avg guesses, 100% solved by turn 4, zero failures |
| Solver performance | **Critical problem.** Worst realistic request takes 14.6s — will hit Vercel's function timeout |
| Analyzer performance | **Fine.** 2–8ms per request |
| Input validation (`next_word`) | ~~None at all~~ → **fixed**. Mostly API-only hardening; one real user-facing typo bug (§1.2) |
| Input validation (`analyze`) | **Good.** Properly validated |
| Frontend | ~~broken font URL, wrong table labels~~ → **fixed**, see §1.5–1.6 |

The single highest-value remaining change is precomputing the pattern matrix. It makes the solver
**~100× faster** and removes the timeout risk entirely.

**Status:** validation, font, and label issues are fixed in this repo. The performance work
(§2) is documented but deliberately not yet applied.

---

## 1. Correctness

### 1.1 The core Wordle pattern algorithm is correct ✅

Both `analyze.py::get_pattern` and `next_word.py::get_pattern_int` implement the two-pass
greens-then-yellows algorithm with correct duplicate-letter accounting.

Validated against an independent `Counter`-based reference implementation over **200,000 random
(guess, answer) pairs: 0 mismatches.** Tricky duplicate cases verified by hand:

| Guess | Answer | Pattern | Correct? |
|---|---|---|---|
| `allow` | `lolly` | `⬛🟨🟩🟨⬛` | ✅ |
| `sassy` | `class` | `🟨🟨⬛🟩⬛` | ✅ |
| `eerie` | `there` | `🟨⬛🟨⬛🟩` | ✅ |
| `robot` | `bloom` | `⬛🟨🟨🟩⬛` | ✅ |

The base-3 encoding (`r0 + r1*3 + r2*9 + r3*27 + r4*81`) is also correct and matches the
243-slot bucket array.

### 1.2 `next_word.py` had no input validation ✅ **Fixed**

`analyze.py` validates carefully (length, dictionary membership, duplicates, count). `next_word.py`
validated *nothing* — it reached straight into `turn["word"]` and `turn["pattern"]`, trusting the
payload completely.

> **⚠️ Severity correction.** An earlier draft of this document ranked this as *critical*. That was
> wrong, and the reachability analysis below is the reason. The frontend constrains tiles to
> `maxLength=1` filtered by `/[^a-zA-Z]/g`, rejects anything that isn't exactly 5 characters, and
> builds patterns via `(current + 1) % 3` — so **9 of the 11 bad payloads below cannot be produced
> by the UI at all.** They are reachable only by calling the API directly.
>
> | Path | Reachable from the web UI? |
> |---|---|
> | missing `word` / `pattern` key | ❌ blocked |
> | short pattern, pattern as string | ❌ blocked |
> | word as int, history not a list | ❌ blocked |
> | word not 5 letters | ❌ blocked (client-side length check) |
> | out-of-range trits | ❌ blocked (`% 3` guarantees 0–2) |
> | duplicate word | ❌ blocked (client checks `finderHistory`) |
> | **unknown 5-letter word** | ✅ **reachable** |
> | **more than 6 turns** | ✅ **reachable** (nothing caps history length) |
>
> The honest framing: this fix is mostly about making the API **correct on its own terms** rather
> than dependent on frontend invariants that aren't enforced anywhere in the backend — plus one
> genuinely reachable bug (below). It is not an urgent production risk. Real severity: **medium.**

**The one bug users can actually hit: typos.** The client checks *length* and *a–z*, never the
dictionary. So `CRANW` (a slip for `CRANE`) sails through and the original code accepts it:

```
CRANE (intended): 35 answers remaining -> ['belly', 'betel', 'bezel', 'bleed', ...]
CRANW (typo)    : 13 answers remaining -> ['bowel', 'swept', 'swift', 'tweed', ...]
overlap with the truth: 5 of 35
```

No error, no warning — a complete ranked recommendation table computed against a word that doesn't
exist, and the real answer isn't necessarily in the list. This is the failure mode worth fixing:
silently wrong beats loudly broken every time, and the user has no signal anything went wrong.

**Class 1 — unhandled crashes (6 paths, API-only).** Any structurally malformed payload raised an
exception out of `do_POST`:

| Input | Original result |
|---|---|
| `[{"word": "crane"}]` (no pattern) | 💥 `KeyError: 'pattern'` |
| `[{"pattern": [0,0,0,0,0]}]` (no word) | 💥 `KeyError: 'word'` |
| `[{"word": "crane", "pattern": [0,0,0]}]` | 💥 `IndexError` — `p[3]` out of range |
| `[{"word": "cran", "pattern": [...]}]` | 💥 `IndexError` — `guess[4]` out of range |
| `[{"word": 123, "pattern": [...]}]` | 💥 `AttributeError` — `int.strip()` |
| `history` not a list | 💥 `TypeError` — string indices |

These surfaced as a bare 500 with **no JSON body**, so the frontend's `await res.json()` threw and
landed in the `catch`, showing `"Network communication failure context."` — pointing the user at
their network when the real problem was their input.

**Class 2 — silent corruption (2 paths).** Worse than the crashes, because nothing looks wrong:

- **Unknown word** — ✅ *reachable from the UI, see the typo example above.* `zzzzz` was accepted;
  `get_pattern_int` compared it against every answer, filtered out the 12 containing a `z`, and
  returned **676 "surviving" answers** plus a full ranked table. Every number real-looking and
  meaningless.
- **Pattern as a string** — ❌ *API-only.* `{"pattern": "00000"}` hits
  `p[0] + p[1]*3 + p[2]*9 + ...`, which on a string is **concatenation, not arithmetic**:
  `"0" + "000" + "000000000" + ...`. No exception, just a target matching nothing, so the API
  confidently reports **0 remaining** — indistinguishable from "your feedback was contradictory."

The unknown-word path is the one that justified the fix on its own. The rest is hardening.

**Fix applied.** Added `validate_history()` in [api/next_word.py](api/next_word.py), called before
any filtering. It rejects with a 400 and a specific message unless: `history` is a list of at most
6 dicts; each `word` is a string that normalizes to a 5-letter entry **present in `guesses.txt`**;
no word repeats; and each `pattern` is a list of exactly 5 integers in `{0,1,2}` (booleans
excluded, since `True == 1` in Python).

Verified — all 12 previously-bad payloads now rejected, all valid ones unaffected:

| Input | Now |
|---|---|
| missing pattern / word key | `Guess 1 needs a 5-tile color pattern.` / `Guess 1 is missing a word.` |
| short pattern, pattern as string | `Guess 1 needs a 5-tile color pattern.` |
| `zzzzz` | `'ZZZZZ' is not a valid Wordle word.` |
| `cran` | `'CRAN' is not 5 letters.` |
| out-of-range trits, `True` as trit | `Guess 1 has an invalid tile color.` |
| word as int | `Guess 1 is missing a word.` |
| history not a list | `Invalid payload: 'history' must be a list.` |
| same word twice | `'CRANE' was entered twice.` |
| 7 turns | `A Wordle game is at most 6 guesses.` |
| `" CRANE "` with whitespace/caps | ✅ accepted (normalized) |
| `crane` + `[0,0,0,0,1]` | ✅ accepted → 35 remaining |

### 1.3 Dead code: the `n_surviving > 3000` branch is unreachable 🐛

```python
if n_surviving > 3000:
    candidate_words = list(set(remaining_words + TOP_GLOBAL_OPENERS))
else:
    candidate_words = GUESSES
```

`remaining_words` starts as `ANSWERS`, which has **688 entries** — and it only shrinks. The
threshold can never be met, so:

- The 50-word `TOP_GLOBAL_OPENERS` list is **never used**.
- Every request always scans the **full 14,855-word** guess list. This is the direct cause of the
  performance problem in §2.
- Two entries in that list (`kares`, `peast`) aren't even in `guesses.txt`, so they'd have been
  invalid suggestions had the branch ever fired.

Note the git history shows answers being removed as they're played (`Remove Aug 13-15 words`), so
the list is shrinking further over time — the branch gets deader, not livelier.

**Fix:** delete the branch and `TOP_GLOBAL_OPENERS`, or repurpose the fast path with a threshold
that reflects the actual pool size (e.g. `n_surviving > 400`).

### 1.4 The `n_surviving > 2` guard — by design ✅ **Not a bug**

When 2 or fewer answers remain, the API returns `top_guesses: []` and the frontend renders an empty
table. This is **intentional**: with two candidates left there is nothing to optimize — you guess
one, and if it's wrong you guess the other. Ranking them would be noise.

For context, this path is common: after a single `raise` opener, **46 of 688 answers (6.7%)** land
in a pool of ≤2.

The only optional tweak would be softening the empty-state copy — `"No values returned."` reads
like a failure rather than "you've already won, just pick one." Behavior itself is correct.

### 1.5 Frontend/backend contract mismatches ✅ **Fixed**

| Location | Said | Actually | Status |
|---|---|---|---|
| `index.html` table header | "Top **30** Mathematical Choices" | backend returns `scored[:20]` — **20** | ✅ fixed |
| Same header | "(Worst Case Minimization)" | sort key is `(expected, worst, in_pool)` — **expected-first** | ✅ fixed |
| Analyzer "Buckets used" | "of 14,348,907 possible" (243ⁿ) | real ceiling is `min(243ⁿ, 688)` = **688** | ⬜ open |

The "Worst Case Minimization" label was the notable one: the code sorts by *expected* remaining
first, which §3.2 shows is genuinely the better policy — so the fix was to the label, not the code.
The header now reads **"Top 20 Mathematical Choices (Expected Remaining Minimization)."**

The 243ⁿ denominator remains open. It's mathematically meaningless for 2–3 words — you cannot have
more buckets than answers. Showing "608 of 14,348,907" implies terrible coverage when 608/688 is
near-perfect separation.

### 1.6 Broken Google Fonts URL ✅ **Fixed**

[`public/index.html:9`](public/index.html#L9) was missing the `?` before `family=`:

```html
<!-- was — fails to load -->
<link href="https://fonts.googleapis.com/css2 family=Inter:wght@400;500;600&...">
<!-- now -->
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&...">
```

Verified: the old URL failed to resolve; the corrected one returns HTTP 200. Both **Inter** and
**Space Grotesk** had been silently falling back to the generic `sans-serif` stack, so the app had
never rendered in its intended typography until now.

### 1.7 Cold-start fragility in `analyze.py` ⚠️

`analyze.py` loads word lists at **module import time** and caches `LOAD_ERROR` in a module global.
If a cold start hits a transient file error, that container returns 500 for **every subsequent
request** until it's recycled.

`next_word.py` uses lazy, retryable loading (`init_words()`), which is the better pattern.
`analyze.py` should adopt it.

### 1.8 Minor

- No client-side dictionary validation in the finder — invalid words make a pointless round trip.
  (The server now rejects them cleanly, so this is a latency nicety, not a correctness issue.)
- Tiles lack `inputmode="text"` and `aria-label`, hurting mobile keyboards and screen readers.
- `switchTab()` doesn't reset per-tab state, so results from a previous session linger when
  switching tabs. Arguably intentional.
- `.env.local` contains a real `VERCEL_OIDC_TOKEN`. It **is** correctly gitignored (`.env*`) ✅ —
  but it's a live credential, so avoid pasting file contents into shared logs.
- **`__pycache__` was committed to the repo** — `api/__pycache__/*.cpython-313.pyc` were tracked
  because `.gitignore` didn't cover them. These are stale bytecode for a Python version that
  doesn't match the deploy runtime, and they bloat the function bundle for no benefit.
  ✅ **Fixed:** added `__pycache__/` and `*.pyc` to `.gitignore` and untracked the two files.

---

## 2. Performance

### 2.1 The solver's worst case exceeds Vercel's function timeout ⚠️ **Critical**

Every request recomputes every pattern from scratch: `len(GUESSES) × n_surviving` calls to
`get_pattern_int`, each allocating two 5-element Python lists.

Measured end-to-end scoring latency in the current implementation:

| Scenario | Pool size | Pattern lookups | Latency |
|---|---|---|---|
| Typical 2nd guess (`crane` → 4 greys + 1 yellow) | 35 | 520K | **1.50s** |
| `raise` all-grey | 49 | 728K | **1.83s** |
| **Worst realistic 1-turn request** (`xviii`) | **466** | 6.9M | **14.63s** |
| Full pool (empty history) | 688 | 10.2M | **18.12s** |

Vercel's Hobby-plan serverless functions default to a **10-second** `maxDuration`, and
`vercel.json` doesn't override it. The 14.6s worst case therefore **times out with a 504** before
returning anything. A user who opens with an obscure word gets a hard failure.

Even the "good" cases are poor UX: **1.5–1.8 seconds of blocking spinner on a typical turn.**

There are 8 guess words that can leave >400 answers remaining; the median worst-case bucket across
all guesses is 149 answers.

### 2.2 The analyzer is fine ✅

| Words | Latency |
|---|---|
| 1 | 1.9ms |
| 2 | 8.0ms |
| 3 | 4.7ms |

It only does `n_words × 688` pattern computations. No action needed.

### 2.3 Prototyped fix: precompute the pattern matrix

The answer list is fixed between deploys, so **every pattern can be computed once, offline.**
A `14,855 × 688` matrix of `uint8` base-3 codes is only **10.2 MB** — trivially within Vercel's
250MB function budget.

At request time, filtering becomes an array slice and scoring becomes a vectorized `bincount`.
I built and benchmarked this:

| Operation | Current | Precomputed + NumPy | Speedup |
|---|---|---|---|
| Full-pool scoring (688 answers) | 18.12s | **0.182s** | **~100×** |
| Narrow pool (35 answers) | 1.256s | **0.039s** | **~32×** |
| Worst realistic request (466) | 14.63s | **~0.13s** | **~110×** |

Supporting costs, all measured:

- Matrix build (offline, one-time): **2.4–2.7s**
- Artifact size: **10.2 MB** raw `.npy`, or **5.1 MB** compressed `.npz`
- Cold-start load: **5ms** from `.npy`, 62ms from `.npz` — use `.npy`

**Validated: 0 mismatches** between the precomputed matrix and the reference implementation over
50,000 random pairs. This is a pure speedup, not an approximation.

Implementation sketch:

```python
# build_matrix.py — run offline, commit data/patterns.npy
M = build_matrix(guess_codes, answer_codes)   # (14855, 688) uint8
np.save("data/patterns.npy", M)

# api/next_word.py — at request time
cols = np.arange(len(ANSWERS))
for turn in history:
    g = GUESS_INDEX[turn["word"]]
    cols = cols[M[g, cols] == encode(turn["pattern"])]

sub  = M[:, cols].astype(np.int64)
offs = (np.arange(NG, dtype=np.int64) * 243)[:, None]
c    = np.bincount((sub + offs).ravel(), minlength=NG * 243).reshape(NG, 243)
worst, expected = c.max(axis=1), (c.astype(float) ** 2).sum(axis=1) / len(cols)
```

Requires adding `numpy` to `requirements.txt`. The comment in `analyze.py` ("no numpy dependency on
serverless") suggests this was deliberately avoided, but NumPy is fully supported on Vercel's
Python runtime and the payoff here is two orders of magnitude.

**No-NumPy fallback:** shipping the same precomputed matrix as a raw `bytes` blob and scoring in
pure Python gives **1.98s** on the full pool — a 9× improvement that stays under the timeout, but
still a visible pause. Worth it only if adding NumPy is off the table.

### 2.4 Other performance notes

- `scored.sort()` sorts all ~14,800 candidates to return 20. `heapq.nsmallest(20, ...)` avoids the
  full sort — negligible next to the scoring cost, but free.
- `counts = [0] * 243` is reallocated per candidate word. Reusing one buffer and clearing only
  touched slots saves meaningful allocation churn in the pure-Python path.
- No HTTP caching. Identical histories recompute from scratch. Since results are fully
  deterministic given the word lists, a `Cache-Control: public, max-age=86400` header (or a small
  in-memory LRU on the history key) would make repeat/shared queries instant.

---

## 3. Solver quality

This is where the project is genuinely strong. I ran a **full simulation over all 688 answers**,
replaying the exact policy in `next_word.py` to completion.

### 3.1 Headline results

Opener `raise`, current `(expected, worst, in_pool)` policy:

| Metric | Value |
|---|---|
| **Average guesses** | **3.0698** |
| Solved in 2 | 66 (9.6%) |
| Solved in 3 | 508 (73.8%) |
| Solved in 4 | 114 (16.6%) |
| Solved in 5+ | **0** |
| **Failures (>6)** | **0** |

**Every single answer is solved by turn 4, with three turns to spare.** For reference, optimal
solvers on the full 2,315-word Wordle answer list average ~3.42; this list is a curated 688 words,
so the pool is easier — but 3.07 with a hard ceiling of 4 is excellent.

### 3.2 The sort policy is the right one ✅

| Policy | Avg guesses | Distribution |
|---|---|---|
| **`expected` first (current)** | **3.0523** | {2: 70, 3: 512, 4: 106} |
| `win_bonus` (credit chance guess *is* the answer) | 3.0523 | identical |
| `worst` first | 3.0799 | {2: 66, 3: 501, 4: 121} |
| `pool_only` when ≤3 remain | 3.0523 | {2: 70, 3: 515, 4: 100, **5: 3**} |

*(rows measured at the best opener; `worst` measured at `raise`)*

Sorting by expected-remaining beats worst-case minimization. `win_bonus` is mathematically
equivalent given the existing `in_pool` tiebreak. Restricting to in-pool words when the pool is
small trades three 4s for three **5s** — strictly worse.

**Conclusion: keep the current sort. Just fix the UI label that claims otherwise (§1.5).**

### 3.3 The ranking metric is not perfectly correlated with actual performance 🔍

An interesting finding. Openers ranked by the tool's own one-ply expected-remaining score, then
evaluated by full simulation:

| Tool's rank | Word | Expected remaining | **Actual avg guesses** |
|---|---|---|---|
| 1 | `raise` | 19.42 | 3.0698 |
| 2 | `raile` | 20.31 | 3.0640 |
| 3 | `arise` | 20.72 | 3.0887 |
| 4 | `ariel` | 21.06 | 3.1003 |
| 5 | `seria` | 21.18 | 3.1076 |
| 6 | `tiare` | 21.25 | 3.0625 |
| 7 | `aesir` | 21.33 | 3.1047 |
| **8** | **`sater`** | **21.42** | **3.0523** ← best |
| 9 | `soare` | 21.72 | 3.0843 |
| 10 | `slier` | 21.87 | 3.0828 |

`sater` ranks **8th** on the metric the analyzer displays, but is the **best actual opener** of the
twelve tested. The greedy one-ply score is a good heuristic, not ground truth — it optimizes the
size of the pool after turn 1, not how cleanly that pool splits on turn 2.

The practical effect is small (0.018 guesses, ~1 extra turn per 57 games), so this is a nuance
worth surfacing in the UI copy rather than a bug. Something like *"ranked by expected pool size
after this guess — a good proxy, not a guarantee of fewest total turns."*

Finding a truly optimal opener requires two-ply lookahead over the top ~50 candidates. With the
precomputed matrix from §2.3 that's roughly a minute offline — very feasible as a build step, not
as a request-time computation.

---

## 4. Recommendations, ranked

### ✅ Done

- **Input validation in `next_word.py`** (§1.2) — guesses must now be real words from
  `guesses.txt`. Fixes the reachable typo bug (`CRANW` → fabricated results); the rest is API
  hardening, since the UI already blocked 9 of 11 bad payloads.
- **Google Fonts URL** (§1.6) — one character; restores the entire intended design.
- **"Top 30" / "Worst Case Minimization" labels** (§1.5) — both were simply wrong.
- **`__pycache__` gitignored and untracked** (§1.8).

### ⬜ Critical — still open

1. **Precompute the pattern matrix** (§2.3). Removes the 14.6s timeout and makes the solver feel
   instant. ~100× speedup, validated as exact. *(Deliberately deferred.)*
2. **Set an explicit `maxDuration`** in `vercel.json` so the limit is visible in the repo rather
   than an implicit plan default. Worth doing even before the matrix work.

### ⬜ High value, low effort

3. **Delete the unreachable `> 3000` branch and `TOP_GLOBAL_OPENERS`** (§1.3) — dead code, and two
   of its entries aren't even valid guesses.
4. **Fix the 243ⁿ bucket denominator** (§1.5) — use `min(243ⁿ, pool_size)`.
5. Make `analyze.py` load lazily like `next_word.py` (§1.7).

### ⬜ Worthwhile

6. Client-side dictionary validation in the finder (§1.8) — saves a round trip.
7. Cache headers or an LRU on the history key (§2.4).
8. `inputmode` / `aria-label` on tiles (§1.8).
9. Soften the ≤2-remaining empty-state copy (§1.4) — behavior is correct, wording reads like an error.

### ⬜ Optional

10. Two-ply opener search as an offline build step (§3.3).
11. Surface the metric's limitation in UI copy (§3.3).

---

## 5. What is already good

Worth stating plainly, since most of this document is problems:

- The Wordle pattern algorithm — the part that's easiest to get subtly wrong — is **exactly right**,
  including every duplicate-letter edge case.
- The solver's decision policy is **empirically optimal** among the alternatives tested.
- Solve quality is excellent: **3.07 average, never worse than 4 guesses, zero failures.**
- `analyze.py`'s input validation is thorough and well-ordered.
- Zero runtime dependencies, no build step, and a clean static-frontend + serverless-function
  split — the architecture is well-matched to the problem.
- `next_word.py`'s lazy-loading pattern is the more robust of the two loading strategies.

The problems are concentrated in **request-time performance** and **input validation on one
endpoint** — not in the mathematics, which is the hard part and is correct.
