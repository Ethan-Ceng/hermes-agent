"""Real model HTTP and inherited SQLite auditing for managed-domain acceptance."""

from http.server import BaseHTTPRequestHandler
import json


class Model(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path != '/v1/chat/completions':
            self.send_error(404)
            return
        self.server.requests.append(body)
        message, finish = self.server.reply(body)
        payload = {'id': 'managed-domain-model', 'model': body.get('model'),
            'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
        kind = 'application/json'
        if body.get('stream'):
            payload['choices'][0]['delta'] = payload['choices'][0].pop('message')
            data = ('data: ' + json.dumps(payload) + '\n\ndata: [DONE]\n\n').encode()
            kind = 'text/event-stream'
        else:
            data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def install_guard(tmp_path):
    guard, audit = tmp_path / 'guard', tmp_path / 'audit'
    guard.mkdir()
    audit.mkdir()
    source = r'''
import atexit,json,os,sqlite3,sys
from pathlib import Path
audit = Path(AUDIT_DIRECTORY)
def record(kind, **extra):
    with (audit / ('events-' + str(os.getpid()) + '.jsonl')).open('a', encoding='utf-8') as output:
        output.write(json.dumps(dict(kind=kind,pid=os.getpid(),parent_pid=os.getppid(),**extra))+'\n')
record('guard')
def reject(*args, **kwargs):
    record('sqlite')
    raise AssertionError('A PG managed domain process attempted SQLite')
sqlite3.connect = reject
sys.addaudithook(lambda event,args: reject() if event == 'sqlite3.connect' else None)
def finished():
    module = sys.modules.get('agent.runtime_session_store')
    worker = bool(module is not None and module.is_worker_process())
    if worker:
        import psutil
        record('worker_exit', ancestors=[parent.pid for parent in psutil.Process().parents()])
atexit.register(finished)
'''.replace('AUDIT_DIRECTORY', repr(str(audit)))
    (guard / 'sitecustomize.py').write_text(source, encoding='utf-8')
    return guard, audit


def records(audit):
    return [json.loads(line) for path in audit.glob('events-*.jsonl')
            for line in path.read_text(encoding='utf-8').splitlines(keepends=True) if line.endswith('\n')]
