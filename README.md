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

**Curated list (688 words):**

| Rank | Word |
|---|---|
| 1 | `raise` |
| 2 | `raile` |
| 3 | `arise` |
| 4 | `ariel` |
| 5 | `seria` |

**Full list (2,341 words):**

| Rank | Word |
|---|---|
| 1 | `roate` |
| 2 | `raise` |
| 3 | `raile` |
| 4 | `tiare` |
| 5 | `soare` |

The finder's UI doesn't let you request a first word — computing it means scoring every guess
against the whole answer list, which is slow. Use the tables above to start instead.

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
- **Curated list has no staleness indicator.** If it's not updated for a while, the bot can
  recommend words Wordle already used. Worth showing a "last updated" date.
- **`TOP_GLOBAL_OPENERS`** (used only if the `>3000` branch fires) has two words not in
  `guesses.txt`: `kares`, `peast`. Fix if that branch ever gets used.
- **`analyze.py` loads word lists at import time**, so a bad cold start fails every request until
  the container recycles. `next_word.py` retries lazily — `analyze.py` should match.
- **No caching.** Same guess history + same pool always gives the same answer. An LRU cache or
  `Cache-Control` header would make repeat queries instant.
- **No client-side dictionary check in the finder.** A typo passes the 5-letter check and gets
  silently scored as a real word. Server now rejects unknown words, but a client-side check would
  save the round trip.
- **Tiles are missing `inputmode` and `aria-label`** — minor mobile/screen-reader gap.
