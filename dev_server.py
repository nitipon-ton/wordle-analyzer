# dev_server.py
import http.server
import os
import sys

# Ensure the root directory is on the path for clean local imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from api.next_word import handler as NextWordHandler
from api.analyze import handler as AnalyzeHandler

class LocalDevRouter(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Configure the static server to target your public directory assets
        super().__init__(*args, directory="public", **kwargs)

    def do_OPTIONS(self):
        if self.path == "/api/next_word":
            NextWordHandler.do_OPTIONS(self)
        elif self.path == "/api/analyze":
            AnalyzeHandler.do_OPTIONS(self)
        else:
            super().do_OPTIONS()

    def do_POST(self):
        if self.path == "/api/next_word":
            NextWordHandler.do_POST(self)
        elif self.path == "/api/analyze":
            AnalyzeHandler.do_POST(self)
        else:
            self.send_error(404, "Endpoint context not found.")

if __name__ == "__main__":
    PORT = 8000
    print(f"🚀 Dev server running smoothly at: http://localhost:{PORT}")
    print("Serving UI from 'public/' and matching endpoints inside 'api/'")
    try:
        http.server.HTTPServer(("", PORT), LocalDevRouter).serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server workspace.")