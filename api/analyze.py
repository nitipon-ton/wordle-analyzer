from http.server import BaseHTTPRequestHandler
import json
import os
import sys

# ---------------------------------------------------------------------------
# Word list loading — bundled in /data relative to repo root
# ---------------------------------------------------------------------------

def load_words(path):
    with open(path) as f:
        return [w.strip().lower() for w in f if len(w.strip()) == 5]

BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ANSWERS_PATH = os.path.join(BASE_DIR, "answers.txt")
GUESSES_PATH = os.path.join(BASE_DIR, "guesses.txt")

try:
    ANSWERS = load_words(ANSWERS_PATH)
    GUESSES_SET = set(load_words(GUESSES_PATH))
except Exception as e:
    ANSWERS = []
    GUESSES_SET = set()
    LOAD_ERROR = str(e)
else:
    LOAD_ERROR = None

# ---------------------------------------------------------------------------
# Core Wordle logic (no numpy dependency on serverless)
# ---------------------------------------------------------------------------

def get_pattern(guess, answer):
    result = [0, 0, 0, 0, 0]
    answer_chars = list(answer)
    for i in range(5):
        if guess[i] == answer[i]:
            result[i] = 2
            answer_chars[i] = None
    for i in range(5):
        if result[i] == 2:
            continue
        if guess[i] in answer_chars:
            result[i] = 1
            answer_chars[answer_chars.index(guess[i])] = None
    return result  # list of 5 trits


def pattern_to_str(trits):
    return "".join(str(t) for t in trits)


def analyze(guess_words, answers):
    n = len(answers)
    from collections import defaultdict
    buckets = defaultdict(int)
    pattern_map = {}  # key -> trits list per word (for display)

    for answer in answers:
        trits_list = [get_pattern(g, answer) for g in guess_words]
        key = tuple(tuple(t) for t in trits_list)
        buckets[key] += 1
        if key not in pattern_map:
            pattern_map[key] = trits_list

    expected = sum(x * x for x in buckets.values()) / n
    worst_key = max(buckets, key=buckets.get)
    worst_case = buckets[worst_key]

    # Top 5 hardest buckets
    top_buckets = sorted(buckets.items(), key=lambda x: -x[1])[:5]
    hardest = []
    for key, count in top_buckets:
        hardest.append({
            "patterns": [list(t) for t in key],
            "count": count,
            "pct": round(count / n * 100, 1),
        })

    return {
        "expected_remaining": round(expected, 2),
        "worst_case": worst_case,
        "worst_patterns": [list(t) for t in worst_key],
        "bucket_count": len(buckets),
        "total_answers": n,
        "hardest_buckets": hardest,
    }


# ---------------------------------------------------------------------------
# Vercel handler
# ---------------------------------------------------------------------------

class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if LOAD_ERROR:
            self._json(500, {"error": f"Word lists failed to load: {LOAD_ERROR}"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            self._json(400, {"error": "Invalid JSON"})
            return

        words = data.get("words", [])

        # Validate
        if not isinstance(words, list) or not 1 <= len(words) <= 3:
            self._json(400, {"error": "Provide 1 to 3 words."})
            return

        words = [w.strip().lower() for w in words]

        for w in words:
            if len(w) != 5:
                self._json(400, {"error": f"'{w}' is not 5 letters."})
                return
            if w not in GUESSES_SET:
                self._json(400, {"error": f"'{w}' is not a valid Wordle word."})
                return

        if len(words) != len(set(words)):
            self._json(400, {"error": "Duplicate words are not allowed."})
            return

        result = analyze(words, ANSWERS)
        result["words"] = words
        self._json(200, result)

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
        pass  # silence default access log
