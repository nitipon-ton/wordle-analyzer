from http.server import BaseHTTPRequestHandler
import json
import os
import numpy as np

# Global variables cached across warm lambda execution contexts
TABLE = None
GUESSES = None
ANSWERS = None
GUESS_INDEX = None
LOAD_ERROR = None

def init_data():
    """Lazy-load data matrices instantly into memory using memory-mapping."""
    global TABLE, GUESSES, ANSWERS, GUESS_INDEX, LOAD_ERROR
    if TABLE is not None:
        return
    try:
        # Match your project's data architecture layout
        base_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        table_path = os.path.join(base_dir, "pattern_table.npy")
        
        # Handle cases where word lists are either text or JSON format
        guesses_path = os.path.join(base_dir, "guesses.txt")
        answers_path = os.path.join(base_dir, "answers.txt")

        # Fallback to JSON if your data folder uses .json suffixes
        if not os.path.exists(guesses_path):
            guesses_path = os.path.join(base_dir, "guesses.json")
            answers_path = os.path.join(base_dir, "answers.json")

        if guesses_path.endswith('.json'):
            with open(guesses_path) as f:
                GUESSES = json.load(f)
            with open(answers_path) as f:
                ANSWERS = json.load(f)
        else:
            with open(guesses_path) as f:
                GUESSES = [w.strip().lower() for w in f if len(w.strip()) == 5]
            with open(answers_path) as f:
                ANSWERS = [w.strip().lower() for w in f if len(w.strip()) == 5]

        # Use memory mapping to bypass heavy cold-start file read bottlenecks
        TABLE = np.load(table_path, mmap_mode='r')
        GUESS_INDEX = {w: i for i, w in enumerate(GUESSES)}
    except Exception as e:
        LOAD_ERROR = str(e)

def encode_trits(trits):
    return trits[0] + trits[1]*3 + trits[2]*9 + trits[3]*27 + trits[4]*81

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        init_data()
        if LOAD_ERROR:
            self._json(500, {"error": f"Lookup assets failed to populate: {LOAD_ERROR}"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._json(400, {"error": "Malformed JSON payload payload."})
            return

        # Expects history: [{"word": "crane", "pattern": [0, 1, 2, 0, 0]}]
        history = data.get("history", [])
        
        # Validate inputs against known dictionaries
        for turn in history:
            w = turn.get("word", "").strip().lower()
            p = turn.get("pattern", [])
            if w not in GUESS_INDEX:
                self._json(400, {"error": f"'{w}' is not a valid guess word."})
                return
            if len(p) != 5 or not all(x in (0, 1, 2) for x in p):
                self._json(400, {"error": "Patterns must be a list of 5 digits containing 0, 1, or 2."})
                return

        # 1. Filter surviving answers based on game history
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

        # 2. Score candidate items dynamically using runtime-safe guardrails
        top_guesses = []
        if n_surviving > 0:
            answer_set = set(remaining_words)
            excluded = set(excluded_indices)

            # Adaptive filtering bypass: Don't scan 13k items if search space is wide
            if n_surviving == len(ANSWERS) or n_surviving > 250:
                # Early Game: Evaluate current candidates plus top metadata openers
                top_defaults = ["raise", "crane", "crate", "slate", "trace", "stare", "audio"]
                default_indices = [GUESS_INDEX[w] for w in top_defaults if w in GUESS_INDEX]
                surviving_guess_indices = [GUESS_INDEX[ANSWERS[idx]] for idx in surviving if ANSWERS[idx] in GUESS_INDEX]
                candidate_indices = list(set(surviving_guess_indices + default_indices))
            else:
                # Late Game: Search space is tight enough to scan all 13,000 words safely (<200ms)
                candidate_indices = range(len(GUESSES))

            sub = TABLE[:, surviving]
            scored = []

            for g_idx in candidate_indices:
                if g_idx in excluded:
                    continue
                counts = np.bincount(sub[g_idx].astype(np.int32), minlength=243)
                worst = int(counts.max())
                expected = float(np.sum(counts ** 2)) / n_surviving
                scored.append((worst, expected, g_idx))

            scored.sort(key=lambda x: (x[0], x[1]))

            for worst, expected, g_idx in scored[:30]:
                w = GUESSES[g_idx]
                top_guesses.append({
                    "word": w,
                    "worst": worst,
                    "expected": round(expected, 2),
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