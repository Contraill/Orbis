"""python tests/provider_fixtures/reference/serve.py [port]

Catalog/HLS metadata fixture. For actual video, generate your own test pattern
media as documented; no copyrighted media or real-site URLs are included.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import os
import hmac

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(Path(__file__).parent),**kwargs)
    def log_message(self,*args): pass  # Do not log synthetic token headers/paths.
    def do_GET(self):
        required=os.environ.get('ORBIS_FIXTURE_TOKEN','')
        if required and not hmac.compare_digest(self.headers.get('X-Fixture-Token',''),required):
            self.send_error(403,'Fixture token required')
            return
        super().do_GET()

if __name__=='__main__':
    ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1]) if len(sys.argv)>1 else 8765),Handler).serve_forever()
