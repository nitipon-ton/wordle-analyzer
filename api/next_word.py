from http.server import BaseHTTPRequestHandler
import json
import os
import numpy as np

# Global data containers cached across warm lambda execution contexts
TABLE = None
GUESSES = None
ANSWERS = None
GUESS_INDEX = None
LOAD_ERROR = None

def init_data():
    """Lazy-load the word indices and pattern matching lookup matrix into memory."""
    global TABLE, GUESSES, ANSWERS, GUESS_INDEX, LOAD_ERROR
    if TABLE is not None:
        return
    try:
        base_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        table_path = os.path.join(base_dir, "pattern_table.npy")
        answers_path = os.path.join(base_dir, "answers.txt")
        guesses_path = os.path.join(base_dir, "guesses.txt")

        # Handle structural deviations dynamically if paths shift under deployment
        if not os.path.exists(table_path):
            base_dir = os.path.join(os.path.dirname(__file__), "data")
            table_path = os.path.join(base_dir, "pattern_table.npy")
            answers_path = os.path.join(base_dir, "answers.txt")
            guesses_path = os.path.join(base_dir, "guesses.txt")

        with open(guesses_path) as f:
            GUESSES = [w.strip().lower() for w in f if len(w.strip()) == 5]
        with open(answers_path) as f:
            ANSWERS = [w.strip().lower() for w in f if len(w.strip()) == 5]

        TABLE = np.load(table_path)
        GUESS_INDEX = {w: i for i, w in enumerate(GUESSES)}
    except Exception as e:
        LOAD_ERROR = str(e)

def encode_trits(trits):
    """Encodes an array of 5 ternary response digits into a single base-3 lookup key."""
    return trits[0] + trits[1]*3 + trits[2]*9 + trits[3]*27 + trits[4]*81

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        init_data()
        if LOAD_ERROR:
            self._json(500, {"error": f"Lookup matrices failed to populate: {LOAD_ERROR}"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._json(400, {"error": "Malformed JSON payload supplied."})
            return

        history = data.get("history", [])
        if not isinstance(history, list):
            self._json(400, {"error": "History must be formatted as an array."})
            return

        # Input Schema Sanitization & Validation
        for turn in history:
            w = turn.get("word", "").strip().lower()
            p = turn.get("pattern", [])
            if w not in GUESS_INDEX:
                self._json(400, {"error": f"'{w}' is not present within standard guess datasets."})
                return
            if len(p) != 5 or not all(x in (0, 1, 2) for x in p):
                self._json(400, {"error": f"Pattern configuration for '{w}' must contain exactly 5 ternary values (0, 1, 2)."})
                return

        # 1. Evaluate remaining candidate subset pool
        mask = np.ones(len(ANSWERS), dtype=bool)
        excluded_indices = []
        for turn in history:
            w = turn["word"].strip().lower()
            p = turn["pattern"]
            g_idx = GUESS_INDEX[w]
            excluded_indices.append(g_idx)
            target = encode_trits(p)
            mask &= (TABLE[g_idx, :] == target)

        surviving = np.where(mask)[0]
        n_surviving = len(surviving)
        remaining_words = [ANSWERS[i] for i in surviving]

        # 2. Score alternative options math strategies
        top_guesses = []
        if n_surviving > 0:
            answer_set = set(remaining_words)

            # Performance bypass optimization: Fast-track turn-1 if nothing has filtered yet
            if n_surviving == len(ANSWERS):
                top_defaults = ["raise", "crane", "crate", "slate", "trace", "roate", "soare", "salet", "carte", "tread"]
                for w in top_defaults:
                    if w in GUESS_INDEX:
                        g_idx = GUESS_INDEX[w]
                        counts = np.bincount(TABLE[g_idx, surviving].astype(np.int32), minlength=243)
                        top_guesses.append({
                            "word": w,
                            "worst": int(counts.max()),
                            "expected": float(np.sum(counts ** 2)) / n_surviving,
                            "in_pool": w in answer_set
                        })
                top_guesses.sort(key=lambda x: (x["worst"], x["expected"]))
            else:
                # Online submatrix calculation pass
                sub = TABLE[:, surviving]
                excluded = set(excluded_indices)
                scored = []

                for g_idx in range(len(GUESSES)):
                    if g_idx in excluded:
                        continue
                    counts = np.bincount(sub[g_idx].astype(np.int32), minlength=243)
                    worst = int(counts.max())
                    expected = float(np.sum(counts ** 2)) / n_surviving
                    scored.append((worst, expected, g_idx))

                scored.sort(key=lambda x: (x[0], x[1]))

                # Map out top 30 highly optimized suggestions
                for worst, expected, g_idx in scored[:30]:
                    w = GUESSES[g_idx]
                    top_guesses.append({
                        "word": w,
                        "worst": worst,
                        "expected": expected,
                        "in_pool": w in answer_set
                    })

        self._json(200, {
            "remaining_count": n_surviving,
            "remaining_words": remaining_words,
            "top_guesses": top_guesses
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

    def log_message(self, *args):
        pass