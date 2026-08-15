# Wordle Toolkit

Two tools for Wordle:

- **Next Word Finder** — enter your guesses and their color feedback, get the best next guess.
- **Opening Analyzer** — enter 1–3 words, see how good they are as openers.

Static frontend (`public/index.html`) + two Python serverless functions
(`api/next_word.py`, `api/analyze.py`) on Vercel.

## Word lists

| File | Words | What it is |
|---|---|---|
| `data/answers.txt` | 688 | Default. Words used in the last 2–3 years removed. Updated every few days. |
| `data/full_answers.txt` | 2,341 | Every official Wordle answer, equally likely. |
| `data/guesses.txt` | 14,855 | Every word accepted as a guess. |

Both tools have a toggle between the curated list and the full list. Switching changes the
reported difficulty, since it changes how many answers are possible.

## Best opening words (as of Aug 15, 2026)

There are two different questions here, and they don't always agree:

- **By the analyzer's metric** — expected answers remaining after one guess. Fast to compute,
  what the Opening Analyzer shows, but only looks one move ahead.
- **By actual play** — average guesses to solve, simulated by playing every answer to completion.
  Slower to compute, but this is the number that actually matters.

**Curated list (688 words) — top 5 by metric:**

| Rank | Word |
|---|---|
| 1 | `raise` |
| 2 | `raile` |
| 3 | `arise` |
| 4 | `ariel` |
| 5 | `seria` |

**Curated list — top 10 by actual play** (avg guesses, all 688 answers simulated; ties broken by
exact guess-count sum, since several average out to the same 4 decimals):

| Rank | Word | Avg guesses |
|---|---|---|
| 1 | `tarse` | 3.0363 |
| 2 | `salet` | 3.0509 |
| 3 | `sater` | 3.0523 |
| 4 | `raine` | 3.0538 |
| 5 | `carse` | 3.0581 |
| 6 | `taser` | 3.0610 |
| 7 | `taler` | 3.0625 |
| 7 | `tiare` | 3.0625 |
| 9 | `raile` | 3.0640 |
| 9 | `reast` | 3.0640 |

**`tarse` beats `raise` (#11, 3.0698) by ~1 extra turn per 30 games** — the metric's #1 pick isn't
the best actual opener. `tarse` ranks only #16 by the one-ply metric, so this is a real find, not
noise: greedy one-ply scoring optimizes the pool size after this guess, not how cleanly that pool
splits next turn, and `tarse` apparently splits its post-turn-1 pools better than words that shrink
the pool more aggressively upfront.

This list combines 34 candidates tested in total: the top 25 by one-ply metric, 9 words suggested
by another Wordle-bot developer, and `carse`. It reflects the best of what's been tested, not an
exhaustive search of all 14,855 guesses.

**Full list (2,341 words) — top 5 by metric:**

| Rank | Word |
|---|---|
| 1 | `roate` |
| 2 | `raise` |
| 3 | `raile` |
| 4 | `tiare` |
| 5 | `soare` |

**Full list — top 10 by actual play** (avg guesses, all 2,341 answers simulated; ties broken by
exact guess-count sum):

| Rank | Word | Avg guesses |
|---|---|---|
| 1 | `tarse` | 3.4468 |
| 2 | `slate` | 3.4485 |
| 2 | `trace` | 3.4485 |
| 4 | `reast` | 3.4490 |
| 5 | `crate` | 3.4498 |
| 6 | `salet` | 3.4537 |
| 6 | `slane` | 3.4537 |
| 8 | `carle` | 3.4549 |
| 9 | `crane` | 3.4571 |
| 10 | `carte` | 3.4596 |

**`tarse` wins on both lists**, beating `roate` — the metric's #1 pick here — by 0.038 guesses,
roughly one extra turn every 26 games. Same pattern as the curated list: `tarse` isn't near the top
of the one-ply metric (outside the top 10 by expected-remaining) but consistently plays better in
full simulation.

**Notably, the entire "suggested by another bot-maker" batch outperforms every classic top-metric
opener here** (`roate`, `raise`, `raile`, `tiare`, `soare` all fall to #13 or lower). `carse` — also
requested and tested — landed just outside, at **#11** (3.4605), edged out by `carte` by 0.0025 of
a guess (2 games out of 2,341).

This list combines 25 candidates: the top 15 by one-ply metric, the same 10 externally-suggested
words, plus `carse`. Reflects the best of what's been tested, not an exhaustive search.

### Three openers worth knowing (full list)

Best average isn't the only thing you might want. Three openers, each optimal for a different goal,
all simulated against every one of the 2,341 answers:

| Guesses | `TARSE` | % | `TRACE` | % | `CARLE` | % |
|---|---|---|---|---|---|---|
| 1 | 0 | 0.00% | 1 | 0.04% | 0 | 0.00% |
| 2 | 62 | 2.65% | 74 | 3.16% | 72 | 3.08% |
| 3 | 1,227 | 52.41% | 1,193 | 50.96% | 1,166 | 49.81% |
| 4 | 997 | 42.59% | 1,020 | 43.57% | 1,069 | 45.66% |
| 5 | 54 | 2.31% | 53 | 2.26% | **34** | **1.45%** |
| 6 | **1** | 0.04% | **0** | 0.00% | **0** | 0.00% |
| Failed (7+) | 0 | 0.00% | 0 | 0.00% | 0 | 0.00% |
| **Average** | **3.4468** | | 3.4485 | | 3.4549 | |
| **Solved ≤4** | 97.65% | | 97.74% | | **98.55%** | |
| **Worst case** | 6 | | **5** | | **5** | |

**Pick by what you care about:**

- **`TARSE` — best average (3.4468).** Wins on raw efficiency, but exactly one answer (`rover`)
  drags it to all six turns.
- **`TRACE` — best average among openers that never need 6 (3.4485).** Costs 0.0017 guesses versus
  `tarse` and buys a hard ceiling of 5. It's also the only one of the three that can win outright on
  turn 1, since `trace` is itself in the answer list.
- **`CARLE` — best chance of finishing by turn 4 (98.55%).** Only **34** answers push it to 5, vs
  53–54 for the others — a **~36% reduction** in the worst realistic case. It pays for this with the
  weakest average of the three, trading 3-guess wins for 4-guess ones.

**Note:** `CARLE` also never needs 6 turns, so both `TRACE` and `CARLE` guarantee a solve in 5. The
distinction is that `TRACE` has the better average, while `CARLE` more often finishes a turn earlier.

If you play to a 6-turn limit and hate close calls, `CARLE` is the safest. If you want the lowest
long-run score, `TARSE`. `TRACE` is the balanced pick.

`TARSE`'s 54 five-guess cases cluster hard around words it tells you nothing about: `young`,
`wound`, `woozy`, `woody`, `wimpy`, `willy`, `wider`, `watch`, `viper`, `vaunt`, `upper`, `ulcer` —
mostly `W`/`V`/`U`/`Y`-heavy words sharing a vowel skeleton `tarse` can't probe.

The finder's UI doesn't let you request a first word — computing it means scoring every guess
against the whole answer list, which is slow. Use the actual-play tables above to start instead.

Regenerate these whenever `answers.txt` is updated.

## How good is the bot

Simulated against every answer, playing to completion:

| | Curated | Full |
|---|---|---|
| Average guesses | 3.07 | 3.49 |
| Worst case | 4 guesses | 5 guesses |
| Failures | 0 | 0 |

3.49 on the full list matches published results for this style of solver. The curated number is
lower only because 688 words is an easier pool — not because the algorithm is better there.

## Known issues / future improvements

- **Solver is slower than it needs to be.** Every request scores all 14,855 guesses, even when
  only a handful of answers remain. Restricting candidates to `remaining answers + known good
  openers` cuts a typical request from ~4s to ~0.05s with no quality loss (tested against the full
  simulation above). The `n_surviving > 3000` branch already does something like this — it's just
  set too high to ever trigger on lists this size. Lowering it (or adding a second threshold) is
  the top item here.
- **A precomputed pattern matrix would be even faster, but doesn't fit.** Vercel's file-size limit
  rejects it — already tried.
- ✅ **Done: curated-list staleness date.** `data/answers_meta.json` holds a `last_updated` date,
  updated whenever `answers.txt` changes. The UI fetches it via a cheap `GET /api/next_word` on
  load (no scoring — just file reads) and shows "List last updated Aug 15, 2026" under the pool
  toggle when on the curated list.
- ✅ **Done: fixed `TOP_GLOBAL_OPENERS`.** Removed `kares` and `peast` — neither is in
  `guesses.txt`.
- **`analyze.py` loads word lists at import time**, so a bad cold start fails every request until
  the container recycles. `next_word.py` retries lazily — `analyze.py` should match.
- **No caching.** Same guess history + same pool always gives the same answer. An LRU cache or
  `Cache-Control` header would make repeat queries instant.
- **No client-side dictionary check in the finder.** A typo passes the 5-letter check and gets
  silently scored as a real word. Server now rejects unknown words, but a client-side check would
  save the round trip.
- **Tiles are missing `inputmode` and `aria-label`** — minor mobile/screen-reader gap.
