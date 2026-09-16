"""Open the existing local workbench, or start it with this repository's Python."""
import argparse
from http.client import HTTPConnection, HTTPException
from pathlib import Path
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'comfyui_py_workflow.local_ui'
SERVER = 'CPWComfyUIWorkbench/'
TITLE = '<title>ComfyUI Workbench</title>'
DEFAULT_PORT = 7860


def running(host, port):
    connection = HTTPConnection(host, port, timeout=2)
    try:
        connection.request('GET', '/')
        response = connection.getresponse()
        return (response.status == 200 and
                response.getheader('Server', '').startswith(SERVER) and
                TITLE in response.read(16384).decode('utf-8'))
    except (OSError, ValueError, HTTPException):
        return False
    finally:
        connection.close()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--view', default='batch')
    parser.add_argument('--no-browser', action='store_true')
    args, extra = parser.parse_known_args(argv)
    # Advanced configurations and help go to the original CLI unchanged.
    reusable = (not extra and args.host in {'127.0.0.1', 'localhost', '::1'} and
                args.view in {'story', 'comic', 'batch', 'settings'})
    host_url = f'[{args.host}]' if ':' in args.host else args.host
    url = f'http://{host_url}:{args.port}/#{args.view}'

    def reopen():
        print(f'Workbench is already running: {url}', flush=True)
        if not args.no_browser and not webbrowser.open(url):
            print(f'Open this address in your browser: {url}', flush=True)
        return 0

    if reusable and running(args.host, args.port):
        return reopen()
    result = subprocess.run([sys.executable, '-m', MODULE, *argv], cwd=ROOT)
    # Another double-click may have won the port while this process was starting.
    if result.returncode and reusable and running(args.host, args.port):
        return reopen()
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
