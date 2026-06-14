from http.server import BaseHTTPRequestHandler
import json
import os

# Tiny global caches for text dictionaries
GUESSES = None
ANSWERS = None
LOAD_ERROR = None

# Hardcoded global high-value openers to evaluate when the search space is wide
TOP_GLOBAL_OPENERS = [
    "raise", "crane", "crate", "slate", "trace", "stare", "audio", "adieu", "salet", "roate", "raile",
    "soare", "arise", "irate", "orate", "ariel", "arose", "raine", "artel", "taler", "ratel", 
    "arles", "realo", "alter", "saner", "later", "snare", "oater", "taser", "tares", "fluke",
    "alert", "reais", "kares", "groin", "chump", "prone", "flame", "gripe", "flair", "grace", 
    "aesir", "carte", "tread", "reast", "peart", "peast", "roast", "pears", "store", "least"
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

        # 2. Pure Python Dynamic scoring loop
        # CHANGED: Skip scoring calculation entirely if 2 or fewer options remain
        if n_surviving > 2:
            if n_surviving > 1500:
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