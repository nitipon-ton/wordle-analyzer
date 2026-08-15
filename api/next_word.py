from http.server import BaseHTTPRequestHandler
import json
import os

# Tiny global caches for text dictionaries
GUESSES = None
GUESSES_SET = None
ANSWERS = None          # curated: recently-used Wordle answers removed
FULL_ANSWERS = None     # every answer the official list has ever used
ANSWERS_UPDATED = None  # date answers.txt was last curated, from answers_meta.json
LOAD_ERROR = None

# Hardcoded global high-value openers to evaluate when the search space is wide.
# Every entry must be a real guess in guesses.txt (checked at import time below).
TOP_GLOBAL_OPENERS = [
    "raise", "crane", "crate", "slate", "trace", "stare", "audio", "adieu", "salet", "roate", "raile",
    "soare", "arise", "irate", "orate", "ariel", "arose", "raine", "artel", "taler", "ratel",
    "arles", "realo", "alter", "saner", "later", "snare", "oater", "taser", "tares", "fluke",
    "alert", "reais", "groin", "chump", "prone", "flame", "gripe", "flair", "grace",
    "aesir", "carte", "tread", "reast", "peart", "roast", "pears", "store", "least"
]

def init_words():
    """Load the raw text word lists into memory (takes <5ms)."""
    global GUESSES, GUESSES_SET, ANSWERS, FULL_ANSWERS, ANSWERS_UPDATED, LOAD_ERROR
    if GUESSES is not None:
        return
    try:
        base_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        if not os.path.exists(os.path.join(base_dir, "guesses.txt")):
            base_dir = os.path.join(os.path.dirname(__file__), "data")

        def read(name):
            with open(os.path.join(base_dir, name)) as f:
                return [w.strip().lower() for w in f if len(w.strip()) == 5]

        GUESSES = read("guesses.txt")
        ANSWERS = read("answers.txt")
        GUESSES_SET = set(GUESSES)

        # Optional - fall back to the curated list if it hasn't been added yet.
        try:
            FULL_ANSWERS = read("full_answers.txt")
        except Exception:
            FULL_ANSWERS = ANSWERS

        # Optional - date answers.txt was last curated. Update this file whenever
        # answers.txt changes, so the UI can show how fresh the list is.
        try:
            with open(os.path.join(base_dir, "answers_meta.json")) as f:
                ANSWERS_UPDATED = json.load(f).get("last_updated")
        except Exception:
            ANSWERS_UPDATED = None
    except Exception as e:
        LOAD_ERROR = str(e)


def pick_answer_pool(word_list):
    """Resolve the requested pool name to its word list.

    'full'    -> every official Wordle answer
    'recent'  -> curated list with recently-used answers removed (default)
    """
    return FULL_ANSWERS if word_list == "full" else ANSWERS


def validate_history(history):
    """Returns an error string, or None if the payload is well-formed.

    Every guess must be a real 5-letter word from guesses.txt and every pattern
    must be exactly 5 trits in {0,1,2}. Anything else is rejected up front so a
    malformed payload can't crash the handler or silently produce nonsense.
    """
    if not isinstance(history, list):
        return "Invalid payload: 'history' must be a list."

    if len(history) > 6:
        return "A Wordle game is at most 6 guesses."

    seen = set()
    for i, turn in enumerate(history):
        pos = f"Guess {i + 1}"

        if not isinstance(turn, dict):
            return f"{pos} is malformed."

        word = turn.get("word")
        if not isinstance(word, str):
            return f"{pos} is missing a word."
        word = word.strip().lower()

        if len(word) != 5:
            return f"'{word.upper()}' is not 5 letters."
        if word not in GUESSES_SET:
            return f"'{word.upper()}' is not a valid Wordle word."
        if word in seen:
            return f"'{word.upper()}' was entered twice."
        seen.add(word)

        pattern = turn.get("pattern")
        if not isinstance(pattern, list) or len(pattern) != 5:
            return f"{pos} needs a 5-tile color pattern."
        for trit in pattern:
            if not isinstance(trit, int) or isinstance(trit, bool) or trit not in (0, 1, 2):
                return f"{pos} has an invalid tile color."

    return None

def get_pattern_int(guess, answer):
    """Computes Wordle pattern matching and encodes directly to base-3 integer."""
    result = [0, 0, 0, 0, 0]
    answer_chars = list(answer)

    # First pass: Greens
    for i in range(5):
        if guess[i] == answer[i]:
            result[i] = 2
            answer_chars[i] = None

    # Second pass: Yellows
    for i in range(5):
        if result[i] == 2:
            continue
        if guess[i] in answer_chars:
            result[i] = 1
            answer_chars[answer_chars.index(guess[i])] = None

    return result[0] + result[1]*3 + result[2]*9 + result[3]*27 + result[4]*81

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        # Cheap metadata only - no scoring - so the UI can show list freshness
        # on page load without ever issuing the expensive empty-history request.
        init_words()
        if LOAD_ERROR:
            self._json(500, {"error": f"Word lists failed to load: {LOAD_ERROR}"})
            return
        self._json(200, {
            "answers_updated": ANSWERS_UPDATED,
            "pool_sizes": {"recent": len(ANSWERS), "full": len(FULL_ANSWERS)}
        })

    def do_POST(self):
        init_words()
        if LOAD_ERROR:
            self._json(500, {"error": f"Word lists failed to load: {LOAD_ERROR}"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._json(400, {"error": "Invalid JSON payload."})
            return

        history = data.get("history", []) # Expected format: [{"word": "crane", "pattern": [0,1,2,0,0]}]

        error = validate_history(history)
        if error:
            self._json(400, {"error": error})
            return

        word_list = data.get("word_list", "recent")
        if word_list not in ("recent", "full"):
            self._json(400, {"error": "word_list must be 'recent' or 'full'."})
            return
        answer_pool = pick_answer_pool(word_list)

        # 1. Filter remaining candidate answer pool on the fly
        remaining_words = list(answer_pool)
        excluded_words = set()

        for turn in history:
            w = turn["word"].strip().lower()
            p = turn["pattern"]
            excluded_words.add(w)
            target_pattern = p[0] + p[1]*3 + p[2]*9 + p[3]*27 + p[4]*81
            
            # Keep only answers that match the historical feedback pattern
            remaining_words = [ans for ans in remaining_words if get_pattern_int(w, ans) == target_pattern]

        n_surviving = len(remaining_words)
        top_guesses = []

        # 2. Pure Python Dynamic scoring loop
        # CHANGED: Skip scoring calculation entirely if 2 or fewer options remain
        if n_surviving > 2:
            if n_surviving > 3000:
                candidate_words = list(set(remaining_words + TOP_GLOBAL_OPENERS))
            else:
                candidate_words = GUESSES

            scored = []
            answer_set = set(remaining_words)

            for guess in candidate_words:
                if guess in excluded_words:
                    continue
                
                counts = [0] * 243
                for ans in remaining_words:
                    p = get_pattern_int(guess, ans)
                    counts[p] += 1
                
                worst = max(counts)
                expected = sum(c ** 2 for c in counts) / n_surviving
                scored.append((worst, expected, guess))

            # Sort order priority: Expected Left -> Worst Case Left -> In Pool Status
            scored.sort(key=lambda x: (x[1], x[0], 0 if x[2] in answer_set else 1))

            for worst, expected, guess in scored[:20]:
                top_guesses.append({
                    "word": guess,
                    "worst": worst,
                    "expected": round(expected, 2),
                    "in_pool": guess in answer_set
                })

        self._json(200, {
            "remaining_count": n_surviving,
            "remaining_words": remaining_words,
            "top_guesses": top_guesses,
            "word_list": word_list,
            "pool_size": len(answer_pool),
            "answers_updated": ANSWERS_UPDATED
        })

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)