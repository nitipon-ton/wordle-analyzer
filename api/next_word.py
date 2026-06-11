from http.server import BaseHTTPRequestHandler
import json
import os
import numpy as np

# Tiny global caches for text dictionaries
GUESSES = None
ANSWERS = None
LOAD_ERROR = None

# Hardcoded global high-value openers to evaluate when the search space is wide
TOP_GLOBAL_OPENERS = [
    "raise", "crane", "crate", "slate", "trace", "stare", "audio", "adieu", "salet",
    "carte", "tread", "reast", "peart", "peast", "roast", "pears", "store", "least"
]

def init_words():
    """Load the raw text word lists into memory (takes <5ms)."""
    global GUESSES, ANSWERS, LOAD_ERROR
    if GUESSES is not None:
        return
    try:
        base_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        guesses_path = os.path.join(base_dir, "guesses.txt")
        answers_path = os.path.join(base_dir, "answers.txt")

        # Fallback to current directory check
        if not os.path.exists(guesses_path):
            base_dir = os.path.join(os.path.dirname(__file__), "data")
            guesses_path = os.path.join(base_dir, "guesses.txt")
            answers_path = os.path.join(base_dir, "answers.txt")

        with open(guesses_path) as f:
            GUESSES = [w.strip().lower() for w in f if len(w.strip()) == 5]
        with open(answers_path) as f:
            ANSWERS = [w.strip().lower() for w in f if len(w.strip()) == 5]
    except Exception as e:
        LOAD_ERROR = str(e)

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
        
        # 1. Filter remaining candidate answer pool on the fly
        remaining_words = list(ANSWERS)
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

        # 2. Dynamic scoring loop (No .npy matrix read needed!)
        if n_surviving > 0:
            # Determine which words are worth evaluating based on pool size to prevent timeouts
            if n_surviving == len(ANSWERS):
                # Turn 1 absolute pristine state bypass
                candidate_words = TOP_GLOBAL_OPENERS
            elif n_surviving > 150:
                # Early/Wide turn: Evaluate surviving options + top informational choices
                candidate_words = list(set(remaining_words + TOP_GLOBAL_OPENERS))
            else:
                # Narrow turn: Fully safe to scan all 12,972 words on-the-fly in milliseconds
                candidate_words = GUESSES

            # Dynamically compute submatrix chunks for active options
            scored = []
            answer_set = set(remaining_words)

            for guess in candidate_words:
                if guess in excluded_words:
                    continue
                
                # Compute array values dynamically on the fly
                patterns = [get_pattern_int(guess, ans) for ans in remaining_words]
                
                # Use numpy tracking on the tiny dynamic array slice
                counts = np.bincount(patterns, minlength=243)
                worst = int(counts.max())
                expected = float(np.sum(counts ** 2)) / n_surviving
                scored.append((worst, expected, guess))

            # Sort by lowest worst-case scenario, breaking ties with expected value
            scored.sort(key=lambda x: (x[0], x[1]))

            for worst, expected, guess in scored[:30]:
                top_guesses.append({
                    "word": guess,
                    "worst": worst,
                    "expected": round(expected, 2),
                    "in_pool": guess in answer_set
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