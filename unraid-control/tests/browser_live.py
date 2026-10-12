"""Serve the real app to verify setup, CSP, secret handling and offline behavior."""
import os
import sys
import tempfile
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright, expect

os.environ.setdefault('CONTROL_DATA', str(Path(tempfile.gettempdir())/'unraid-control-test-bootstrap'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control.main import create_app


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app(directory)
        app.state.unraid.capabilities = lambda:[]
        app.state.unraid.read = lambda section, fresh=False:{'data':None,'sampled_at':None,'stale':False,'error':'Server not connected.'}
        # Bridge browser HTTP requests into the real ASGI app; preserve its
        # authentication/cookies/middleware/static responses without a fake API.
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args): pass

            def respond(self):
                body = self.rfile.read(int(self.headers.get('content-length',0)))
                with TestClient(app,base_url='http://'+self.headers['host']) as client:
                    response = client.request(self.command,self.path,headers=dict(self.headers),content=body)
                self.send_response(response.status_code)
                for key,value in response.headers.multi_items():
                    if key.lower() not in ('transfer-encoding','connection'):
                        self.send_header(key,value)
                self.end_headers()
                self.wfile.write(response.content)

            do_GET = do_POST = do_PUT = respond
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                options = {'headless':True}
                if os.getenv('CONTROL_BROWSER_EXECUTABLE'): options['executable_path'] = os.environ['CONTROL_BROWSER_EXECUTABLE']
                browser = p.chromium.launch(**options)
                page = browser.new_page(viewport={'width':1200,'height':900})
                errors = []
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('console',lambda message:errors.append(message.text) if 'Content Security Policy' in message.text else None)
                page.goto('http://127.0.0.1:'+str(server.server_port))
                expect(page.locator('#accessDialog')).to_be_visible()
                page.locator('#accessPassword').fill('local-test-password')
                page.locator('#accessForm button').click()
                expect(page.locator('#accessDialog')).not_to_be_visible()
                expect(page.locator('#notice')).to_contain_text('Server not connected')
                page.locator('.nav-link[data-page=settings]').click()
                page.locator('[name=url]').fill('https://example.test')
                page.locator('[name=api_key]').fill('private-test-token')
                page.locator('#settingsForm [type=submit]').click()
                expect(page.locator('#settingsMessage')).to_contain_text('Settings saved')
                result = page.evaluate('fetch("/api/settings").then(r=>r.json())')
                assert result['api_key_configured']
                assert 'private-test-token' not in str(result)
                page.reload()
                expect(page.locator('[name=api_key]')).to_have_value('')
                page.locator('[name=login_required]').uncheck()
                page.locator('#settingsForm [type=submit]').click()
                expect(page.locator('#settingsMessage')).to_contain_text('Settings saved')
                page.context.clear_cookies()
                page.reload()
                expect(page.locator('#accessDialog')).not_to_be_visible()
                page.locator('.nav-link[data-page=services]').click()
                page.locator('#addTile').click()
                page.locator('#tileName').fill('Local console')
                page.locator('#tileUrl').fill('https://example.test/Tools')
                page.locator('#tileForm [type=submit]').click()
                expect(page.locator('.service-tile')).to_have_count(1)
                page.reload()
                expect(page.locator('.service-tile')).to_have_count(1)
                assert not errors, errors
                browser.close()
                print('PASS: real FastAPI app, setup/session, CSP, credential privacy, optional login, tiles and offline containment')
        finally:
            server.shutdown()
            thread.join(timeout=10)
            server.server_close()


if __name__ == '__main__': main()
