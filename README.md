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

**Curated list — top 10 by actual play** (avg guesses, all 688 answers simulated):

| Rank | Word | Avg guesses |
|---|---|---|
| 1 | `tarse` | 3.0363 |
| 2 | `salet` | 3.0509 |
| 3 | `sater` | 3.0523 |
| 4 | `raine` | 3.0538 |
| 5 | `taser` | 3.0610 |
| 6 | `tiare` | 3.0625 |
| 7 | `taler` | 3.0625 |
| 8 | `raile` | 3.0640 |
| 9 | `raise` | 3.0698 |
| 10 | `laser` | 3.0770 |

**`tarse` beats `raise` by ~1 extra turn per 30 games** — the metric's #1 pick isn't the best
actual opener. It ranks well on the metric too (#16), so it's a real find, not noise: greedy
one-ply scoring optimizes the pool size after this guess, not how cleanly that pool splits next
turn, and `tarse` apparently splits its post-turn-1 pools better than words that shrink the pool
more aggressively upfront.

**Full list (2,341 words) — top 5 by metric:**

| Rank | Word |
|---|---|
| 1 | `roate` |
| 2 | `raise` |
| 3 | `raile` |
| 4 | `tiare` |
| 5 | `soare` |

**Full list — top 10 by actual play** (avg guesses, all 2,341 answers simulated):

| Rank | Word | Avg guesses |
|---|---|---|
| 1 | `tarse` | 3.4468 |
| 2 | `ranse` | 3.4729 |
| 3 | `tiare` | 3.4737 |
| 4 | `artel` | 3.4827 |
| 5 | `roate` | 3.4848 |
| 6 | `soare` | 3.4861 |
| 7 | `raile` | 3.4891 |
| 8 | `raise` | 3.4908 |
| 9 | `raine` | 3.4912 |
| 10 | `taler` | 3.4938 |

**`tarse` wins on both lists.** It beats `roate` — the metric's #1 pick here — by 0.038 guesses,
roughly one extra turn every 26 games. Same pattern as the curated list: `tarse` isn't near the top
of the one-ply metric (it's outside the top 10 by expected-remaining) but consistently plays better
in full simulation.

A batch of 10 words suggested by another Wordle-bot developer (`salet`, `reast`, `crate`, `trace`,
`slate`, `crane`, `carle`, `slane`, `carte`, `torse`) is being simulated against both lists to check
whether any beat `tarse` — results to follow.

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
