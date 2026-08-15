# Wordle Toolkit — Engineering Analysis

Analysis of the solver bot (`api/next_word.py`), the opening analyzer (`api/analyze.py`), and the
frontend (`public/index.html`). Covers correctness, performance, and solver quality, with
measured benchmarks and prototyped alternatives.

Measured on: Python 3.14.6, Windows 11.

## Word lists

| File | Words | What it is |
|---|---|---|
| `data/answers.txt` | **688** | **Default.** Curated — answers Wordle used in roughly the last 2–3 years are removed. Hand-updated every few days as new answers are played. Reflects what Wordle can still pick *today* (as of Aug 2026). |
| `data/full_answers.txt` | **2,341** | Every official Wordle answer, treated as equally likely — including ones already used. The theoretical baseline. |
| `data/guesses.txt` | **14,855** | Every word accepted as a *guess*. Candidate pool for recommendations. |

Verified relationships: `answers.txt` ⊂ `full_answers.txt` ⊂ `guesses.txt`, all entries 5 letters
and alphabetic, no duplicates. The curated list has **1,653 words removed — 70.6% of the full
list.**

Both endpoints accept a `word_list` parameter (`"recent"` — default — or `"full"`), and the UI
exposes it as a toggle on both tabs. See §4.

---

## TL;DR

| Area | Verdict |
|---|---|
| Wordle pattern logic | **Correct.** 0 mismatches vs an independent reference over 200,000 random pairs |
| Solver quality | **Very strong.** 3.07 avg guesses on the curated list, 100% solved by turn 4, zero failures |
| Solver performance | **Slow, not broken.** 1.3s typical curated; **3.9s typical / 50.4s worst** on the full list. Fixable to **0.05s / 4.6s** with no new dependency (§2.5) |
| Analyzer performance | **Fine.** 2–8ms per request, both pools |
| Input validation (`next_word`) | ~~None at all~~ → **fixed**. Mostly API-only hardening; one real user-facing typo bug (§1.2) |
| Input validation (`analyze`) | **Good.** Properly validated |
| Frontend | ~~broken font URL, wrong table labels, 243ⁿ denominator~~ → **fixed**, see §1.5–1.6 |
| Answer-pool toggle | **Added** (§4). Changes reported difficulty ~2.75×, so labelling it in the UI matters |

The highest-value remaining change is **restricting the candidate guess set** (§2.5) — up to 167×
faster with **zero measured quality loss**, no new dependency, and nothing shipped. A precomputed
matrix would be faster still but **cannot be deployed** under Vercel's file-size limits (§2.3).

**Status:** validation, font, label, denominator, and toggle work are applied in this repo. The
performance work (§2.5) is documented but deliberately not yet applied.

> **Corrections from earlier drafts, kept visible rather than quietly edited out.** Three claims
> in this document were wrong and have been retracted in place:
>
> 1. **Input-validation severity was overstated** (§1.2) — the UI blocks 9 of the 11 payloads.
> 2. **The Vercel timeout claim was wrong** (§2.1) — asserted from memory, never verified, and
>    disproven by the owner's own production testing.
> 3. **The `> 3000` branch is not dead code** (§1.3) — it's a deliberate guard for larger test
>    lists, and the recommendation to delete it was mistaken.
>
> A fourth recommendation — shipping a precomputed matrix — is **not wrong but not deployable**,
> blocked by Vercel file-size limits the owner had already hit (§2.3–2.4).

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

### 1.3 The `n_surviving > 3000` branch — deliberate, currently inactive ✅ **Not a bug**

> *An earlier draft of this section called this dead code and recommended deleting it. **That was
> wrong.** The threshold is an intentional guard kept in place for testing larger word lists that
> don't ship in this repo. It is inactive at current list sizes, not vestigial. The one genuine
> finding below — two invalid words in `TOP_GLOBAL_OPENERS` — still stands.*

The branch never fires today: `full_answers.txt` is 2,341 words and `answers.txt` is 688, both
under 3,000. So every request currently scans all 14,855 guesses, which is the direct cause of the
latency in §2.1 — but that's a consequence of the threshold being *high*, not of the branch being
useless. §2.5 recommends adding a second, lower threshold rather than touching this one.

**One real defect:** two entries in `TOP_GLOBAL_OPENERS` — `kares` and `peast` — are **not in
`guesses.txt`**. If the guard ever activates on a larger list, it would offer two words Wordle
won't accept. Worth fixing now, while the branch is dormant and harmless.

<details>
<summary>Original finding (superseded)</summary>

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

</details>

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

### 2.1 The solver is slow, and the full list makes it much slower ⚠️

Every request recomputes every pattern from scratch: `len(GUESSES) × n_surviving` calls to
`get_pattern_int`, each allocating two 5-element Python lists.

> **⚠️ Correction.** An earlier draft claimed these latencies would trip a 10s Vercel timeout and
> return a 504. **That was an unverified assertion, and the project owner has since tested it in
> production — Vercel handles these requests without breaking.** Modern Vercel (Fluid Compute)
> allows far longer than the 10s I assumed. The latencies below are measured and stand; the
> *timeout conclusion drawn from them was wrong* and has been removed. This is a **UX-latency**
> problem, not an availability one.

Measured end-to-end scoring latency in the current implementation:

| Scenario | Pool | n remaining | Latency |
|---|---|---|---|
| Typical 2nd guess (`crane` → 4 greys + 1 yellow) | curated | 35 | **1.26s** |
| `raise` all-grey | curated | 49 | **1.74s** |
| Worst realistic 1-turn request (`xviii`) | curated | 466 | **14.6s** |
| Typical 2nd guess | **full** | 128 | **3.93s** |
| `raise` all-grey | **full** | 170 | **5.00s** |
| **Worst realistic 1-turn request** (`xviii`) | **full** | **1,567** | **50.4s** |

The full list is 3.4× the answers, and cost scales linearly with the surviving pool — so every
number roughly triples. A typical turn goes from ~1.3s to ~3.9s, and the worst case from 14.6s to
**50.4s**.

There are 8 guess words that can leave >400 answers on the curated list; the median worst-case
bucket across all guesses is 149 (curated) and 507 (full).

### 2.2 The analyzer is fine ✅

| Words | Latency |
|---|---|
| 1 | 1.9ms |
| 2 | 8.0ms |
| 3 | 4.7ms |

It only does `n_words × 688` pattern computations. No action needed.

### 2.3 Design constraints that rule options out

Three deliberate constraints, confirmed by the project owner, that any performance proposal has to
respect:

1. **The UI forbids an empty guess history.** You cannot ask the solver for a first word — that
   would mean scoring all 14,855 guesses against the entire pool, the single most expensive
   operation possible (18s curated / ~62s full). Blocking it in the UI is an intentional trade:
   worse discoverability in exchange for never issuing that request. **Any benchmark row for
   "empty history" below is therefore unreachable in practice** and is kept only as an upper bound.
2. **Vercel's file-size limits block shipping a precomputed matrix.** Already attempted and
   rejected in practice. The 10.2 MB / 34.8 MB artifacts proposed in §2.4 **cannot be deployed**,
   which invalidates that recommendation as originally written. See §2.5 for what works instead.
3. **The `n_surviving > 3000` branch is deliberate**, not dead code. It's a guard kept in place for
   testing larger word lists that don't ship here. It is simply inactive at current list sizes
   (688 and 2,341). *An earlier draft called this dead code and recommended deleting it — that was
   wrong.*

**The one real cost of constraint 1** is that users must source a good opening word themselves —
the tool can't tell them. §2.6 closes that gap for free.

### 2.4 Prototyped fix: precompute the pattern matrix ❌ **Not deployable**

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

**❌ This cannot ship.** Vercel's file-size limits reject the artifact (§2.3, constraint 2) — the
owner tested this. The numbers above are retained only as an upper bound on what's theoretically
achievable, and to show the algorithm isn't the bottleneck. **Do not act on this section.**

### 2.5 What actually works: restrict the candidate set ✅ **Recommended**

The expensive dimension isn't the answer pool, it's the **14,855 candidate guesses** scored against
it. Almost all of those are terrible guesses that get scored in full every request.

Restricting candidates to `remaining_answers ∪ known_good_openers` — exactly the mechanism the
existing `n_surviving > 3000` branch already implements, just with a threshold low enough to
activate — is dramatically cheaper. **In pure Python, no new dependency, nothing shipped:**

| Pool | Scenario | n | All 14,855 | Restricted | Candidates | Speedup |
|---|---|---|---|---|---|---|
| curated | worst | 466 | 13.18s | **0.45s** | 508 | **29×** |
| curated | typical | 35 | 1.32s | **0.01s** | 84 | **167×** |
| full | worst | 1,567 | 43.07s | **4.63s** | 1,596 | **9×** |
| full | typical | 128 | 3.81s | **0.05s** | 177 | **79×** |

**The quality cost is zero.** Simulating all 688 curated answers at thresholds of 400, 200, 100 and
50 produced **byte-identical outcome distributions** to scoring all 14,855 candidates —
`{2: 66, 3: 508, 4: 114}`, average 3.0698, every time. Not "close enough": identical.

That result makes intuitive sense. When many answers remain, the pool itself contains plenty of
high-information guesses, so the exotic non-answer separators that justify scanning the full
dictionary only matter in narrow endgames — precisely where the threshold turns the restriction
*off* and full scanning resumes.

**Recommendation: keep the `> 3000` guard for large-list testing, and add a second, lower
activation threshold (~100–200) that applies to the lists actually in use.** This is the single
best performance change available under the deployment constraints: a typical full-list turn drops
from 3.81s to **0.05s**, and the 50s worst case to **4.6s**, with no new dependency, no shipped
artifact, and no measured quality loss.

**Optional stacking:** NumPy vectorisation *computed at request time* (no precomputed file, so no
size limit) independently gives ~7× — full-list worst case 50.4s → **7.14s**, typical 3.93s →
**0.57s**. It costs a `requirements.txt` dependency and would compose with the restriction above,
but the restriction alone is cheaper and more effective.

### 2.6 Closing the "what's my first word?" gap 🆕

Since the UI intentionally can't compute an opening word (§2.3, constraint 1), users have to find
one elsewhere. This is solvable **entirely offline at zero runtime cost**: the best openers are a
fixed property of each word list, so they can be computed once and shipped as a static table.

Generated for both pools — the complete JSON is **2,162 bytes**:

| Rank | Curated (688) | Expected left | Full (2,341) | Expected left |
|---|---|---|---|---|
| 1 | `raise` | 19.42 | `roate` | 61.17 |
| 2 | `raile` | 20.31 | `raise` | 61.64 |
| 3 | `arise` | 20.72 | `raile` | 61.88 |
| 4 | `ariel` | 21.06 | `tiare` | 61.92 |
| 5 | `seria` | 21.18 | `soare` | 62.77 |

Note the lists **disagree on the best opener** — further reason the pool toggle must stay visible.

Two ways to surface it, both cheap:
- Show the top few as clickable suggestions under the empty finder input ("Not sure? Start with
  **RAISE**"), filtered by the active pool. One click fills the tiles.
- Or simply pre-fill the input with the top opener for the active pool.

This recovers essentially all the discoverability lost to constraint 1, without ever issuing the
expensive empty-history request. Regenerate the table whenever `answers.txt` is updated.

### 2.7 Other performance notes

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

Opener `raise`, current `(expected, worst, in_pool)` policy, every answer played to completion:

| Metric | Curated (688) | Full (2,341) |
|---|---|---|
| **Average guesses** | **3.0698** | **3.4908** |
| Solved in 1 | — | 1 |
| Solved in 2 | 66 (9.6%) | 56 (2.4%) |
| Solved in 3 | 508 (73.8%) | 1,139 (48.7%) |
| Solved in 4 | 114 (16.6%) | 1,083 (46.3%) |
| Solved in 5 | 0 | 62 (2.6%) |
| Solved in 6+ | **0** | **0** |
| **Failures (>6)** | **0** | **0** |

**Zero failures on either pool.** On the curated list every answer is solved by turn 4, with two
turns to spare; on the full list, by turn 5.

The full-list number is the meaningful benchmark, because it's the one comparable to published
results — and **3.49 sits right in the band of strong published Wordle solvers (~3.42–3.55)** for
greedy one-ply strategies. That's a genuine, independently-verifiable validation that the solver
logic is sound, not just internally consistent.

The curated list's 3.07 is better only because a 688-word pool is intrinsically easier than a
2,341-word one — it is *not* evidence of a better algorithm, and the two numbers should never be
compared to each other.

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

*(curated list. The full list ranks openers differently — `roate` 61.2, `raise` 61.6, `raile` 61.9,
`tiare` 61.9, `soare` 62.8 — which is itself a reason the pool toggle needs to be visible in the
UI: **the "best opening word" is not the same question on both pools.**)*

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

**The divergence looks smaller on the full list**, which is worth noting because it suggests the
curated pool is part of the cause:

| Opener | Metric rank (full) | Expected remaining | Actual avg | 5-guess games |
|---|---|---|---|---|
| `roate` | **1** | 61.2 | **3.4848** ← best | 41 |
| `raise` | 2 | 61.6 | 3.4908 | 62 |

Here the metric's top pick *does* win. This is only a two-opener check, so treat it as suggestive
rather than settled — but it's consistent with the idea that a 688-word pool has enough
granularity noise to scramble a ranking that holds up better over 2,341 words. Note also that
`roate` produces **a third fewer 5-guess games** (41 vs 62) at nearly the same average, i.e. it's
the more *consistent* opener — a dimension the current single-number ranking doesn't express at
all.

Finding a truly optimal opener requires two-ply lookahead over the top ~50 candidates — roughly a
minute of offline computation. That's fine as a build step feeding the static opener table in §2.6;
it is never viable as a request-time computation.

---

## 4. The answer-pool toggle

Both tools now score against either pool, selected by a toggle in the UI and a `word_list`
parameter on both endpoints (`"recent"` default, or `"full"`).

### 4.1 Why the choice actually matters

This isn't a cosmetic switch — it changes every number the tools report, because it changes the
prior over answers:

- **`recent` (688 words)** assumes Wordle won't reuse an answer from the last few years. Given the
  official game has never repeated an answer, this is the **correct model for playing today**, and
  it's a far sharper prior — you start with 688 candidates instead of 2,341.
- **`full` (2,341 words)** assumes every official answer is equally likely. This is the right model
  for **theoretical comparisons** — it's what published solver benchmarks use, so it's the only
  way to compare this tool's numbers against anyone else's.

Same opener, same code, very different reported difficulty:

| `crane` as an opener | Curated (688) | Full (2,341) |
|---|---|---|
| Expected answers remaining | **29.05** | **79.99** |
| Worst-case bucket | **100** | **267** |
| Answer pool | 688 | 2,341 |

Roughly a 2.75× difference in expected remaining. Neither is wrong — they answer different
questions. **The important part is that the UI now says which one you're looking at**, because
"29 remaining" and "80 remaining" for the same word is otherwise inexplicable.

### 4.2 The curated list is the harder engineering case, not the easier one

Counter-intuitively, keeping the curated list current is the **fragile** part of this design:

- It's **hand-maintained every few days**. Miss a few days and the tool silently recommends words
  Wordle already used — the exact failure mode the list exists to prevent. There's no staleness
  indicator anywhere in the UI.
- It **shrinks monotonically**. At 688 and falling, the already-dead `n_surviving > 3000` branch
  (§1.3) gets deader, and eventually the pool gets small enough that most turns end in the ≤2 case
  (§1.4).
- A **stale curated list is worse than the full list**, because it's confidently wrong rather than
  merely conservative. The full list can never exclude the true answer; the curated one can.

Worth considering: derive `answers.txt` from `full_answers.txt` minus a dated
`used_words.txt`, so the removal is reproducible and the "last updated" date is visible rather than
implicit in git history.

### 4.3 Performance impact — this is where it bites

The full list is 3.4× the answers, and scoring cost is linear in the surviving pool:

| | Curated (688) | Full (2,341) | Factor |
|---|---|---|---|
| Typical turn | 1.26s | **3.93s** | 3.1× |
| `raise` all-grey | 1.74s | **5.00s** | 2.9× |
| Worst realistic turn | 14.6s | **50.4s** | 3.5× |
| Worst-case pool after 1 turn | 466 | **1,567** | 3.4× |

**A 50-second request is the headline risk of enabling the full list.** Vercel tolerates it (§2.1),
so this is a UX problem rather than an outage — but a 50s spinner is effectively a broken feature,
and users will assume the page hung.

The precomputed matrix would solve this outright (0.272s for the whole 2,341-word pool) but
**can't be deployed** — the 34.8 MB artifact exceeds Vercel's file-size limits (§2.3). The viable
answer is candidate restriction (§2.5), which brings the full list's typical turn to **0.05s** and
its worst case to **4.6s** using nothing but a lower threshold on logic already in the file.

**Recommendation: land the candidate restriction before making `full` the default.** As shipped,
`recent` remains the default, keeping typical latency near ~1.3s.

### 4.4 Implementation notes

- `word_list` is validated against `{"recent", "full"}` and rejected with a 400 otherwise, matching
  the validation added in §1.2.
- `full_answers.txt` loads **optionally** — if the file is missing, both endpoints fall back to the
  curated list rather than failing. The toggle degrades to a no-op instead of a 500.
- The API echoes `word_list` (and `pool_size`) in its response, so the client can confirm which
  pool produced a result rather than assuming.
- Switching pools **hides stale results** on both tabs, since numbers computed against the other
  pool no longer describe anything on screen. The finder's guess *history* stays valid — it's just
  re-scored against the new pool automatically.
- ⚠️ **`data/full_answers.txt` is currently untracked.** It must be committed, or the deployed
  functions will silently fall back to the curated list for both toggle positions.

---

## 5. Recommendations, ranked

### ✅ Done

- **Input validation in `next_word.py`** (§1.2) — guesses must now be real words from
  `guesses.txt`. Fixes the reachable typo bug (`CRANW` → fabricated results); the rest is API
  hardening, since the UI already blocked 9 of 11 bad payloads.
- **Google Fonts URL** (§1.6) — one character; restores the entire intended design.
- **"Top 30" / "Worst Case Minimization" labels** (§1.5) — both were simply wrong.
- **243ⁿ bucket denominator** (§1.5) — now `min(243ⁿ, pool_size)`.
- **Answer-pool toggle** (§4) — `recent` / `full` on both endpoints and both tabs.
- **`__pycache__` gitignored and untracked** (§1.8).

### ⬜ Do this first

1. **Commit `data/full_answers.txt`** (§4.4). It's untracked — without it the deployed toggle
   silently does nothing.

### ⬜ High value

2. **Add a low candidate-restriction threshold (~100–200)** alongside the existing `> 3000` guard
   (§2.5). Pure Python, no dependency, nothing shipped, **zero measured quality loss** — and it
   takes a typical full-list turn from 3.81s to **0.05s**, worst case 43s → **4.6s**. This is the
   single highest-value change available under the deployment constraints.
3. **Ship the precomputed opener table** (§2.6). 2 KB, offline-generated, and it recovers the
   discoverability deliberately traded away by blocking empty-history requests — the one real cost
   of that design choice.
4. **Fix the two invalid entries in `TOP_GLOBAL_OPENERS`** (§1.3) — `kares` and `peast` aren't in
   `guesses.txt`, so if the `> 3000` guard ever activates on a larger list it would surface two
   unusable words. The branch itself is deliberate and should stay.
5. **Surface curated-list staleness** (§4.2) — a "last updated" date, or derive `answers.txt` from
   `full_answers.txt` minus a dated `used_words.txt`.
6. Make `analyze.py` load lazily like `next_word.py` (§1.7).

### ❌ Ruled out

- **Precomputed pattern matrix** (§2.4) — blocked by Vercel file-size limits; already tested.
- **Deleting the `> 3000` branch** — it's an intentional guard for larger test lists.
- **Computing a best opening word on demand** — intentionally blocked in the UI; §2.6 solves the
  underlying need offline instead.

### ⬜ Worthwhile

7. Client-side dictionary validation in the finder (§1.8) — saves a round trip.
8. Cache headers or an LRU on `(history, word_list)` (§2.4) — results are fully deterministic.
9. `inputmode` / `aria-label` on tiles (§1.8).
10. Soften the ≤2-remaining empty-state copy (§1.4) — behavior is correct, wording reads like an error.

### ⬜ Optional

11. Two-ply opener search as an offline build step (§3.3).
12. Surface the metric's limitation in UI copy (§3.3).

---

## 6. What is already good

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
