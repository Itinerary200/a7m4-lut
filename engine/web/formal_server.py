"""Portable Mac formal workbench: native12 -> grid5 -> stack3 -> BIN audit."""
from pathlib import Path
import argparse
import copy
import json
import os
import sys
import threading
import time
import traceback
import uuid

HERE = Path(__file__).resolve().parent
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ.setdefault(key, '1')
os.environ.update(R5_GPU_TRAINING='1', R5_GPU_STRICT='1',
    PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
if sys.platform == 'win32' and not sys.flags.utf8_mode:
    os.execve(sys.executable, [sys.executable, '-X', 'utf8', *sys.argv], os.environ.copy())
sys.path[:0] = [str(HERE), str(HERE.parent/'scripts')]
import gpu_runtime
import server
import batch_training
from stack_training import train, save
from training_progress import TrainingProgress

PROFILE = json.loads((HERE/'formal_profile.json').read_text(encoding='utf-8'))
SETTINGS = PROFILE['settings']
original_work = server.work
original_validate = server.validate_fit
original_completed = batch_training.completed_continuation


def validate(body):
    # Identity and names belong to the user's upload; all training controls
    # are bound to the same versioned formal recipe, including API callers.
    body.update(copy.deepcopy(PROFILE['options']))
    return original_validate(body)


def completed(identifier, job, srv):
    path = srv.RUNS/identifier/'stack_audit.json'
    if not path.exists():
        return False
    audit = json.loads(path.read_text())
    if (audit['settings'] != SETTINGS or not audit['bin_decode_recompile']
            or not audit['decoded_native_cpu_replay']):
        raise ValueError('Formal stack audit mismatch')
    from grid_distillation import load_result
    load_result(srv.RUNS/identifier, job['result']['grid_key'])
    if srv.core.sha((srv.RUNS/identifier/'R5NATIVE.BIN').read_bytes()) != audit['binary_sha256']:
        raise ValueError('Formal BIN identity mismatch')
    return True


def formal_work(identifier, options, resume=False):
    final = server.JOBS[identifier]
    out = server.RUNS/identifier
    out.mkdir(exist_ok=True)
    # Restart preserves the expensive native parent and its target identity.
    prior = json.loads((out/'job.json').read_text()) if (out/'job.json').exists() else {}
    baseid = prior.get('base_job') or uuid.uuid4().hex
    source = server.RUNS/baseid
    base = json.loads((source/'job.json').read_text()) if (source/'job.json').exists() else dict(
        id=baseid, status='queued', target_kind=options.get('target_kind'), started=time.time(), phase='原生基准准备')
    server.JOBS[baseid] = base
    final.update(status='running', base_job=baseid, phase='正式方案：原生12起点基准')
    save(out/'job.json', final)
    stop = threading.Event()

    def mirror():
        while not stop.wait(1):
            try:
                final['phase'] = '正式基准：' + base.get('phase', '训练中')
                for name in ('training_progress.json', 'grid_progress.json'):
                    if (source/name).exists():
                        save(out/name, json.loads((source/name).read_text()))
                progress_name = ('grid_progress.json' if base.get('status') == 'done'
                    or '压缩训练' in base.get('phase', '') else 'training_progress.json')
                if (source/progress_name).exists():
                    save(out/'training_progress.json', json.loads((source/progress_name).read_text()))
                save(out/'job.json', {k:v for k,v in final.items() if k != 'process'})
            except (OSError, ValueError):
                pass

    thread = threading.Thread(target=mirror, daemon=True)
    thread.start()
    try:
        if base.get('status') != 'done':
            original_work(baseid, options, resume=source.exists())
        if base['status'] != 'done':
            raise RuntimeError(base.get('error', 'Native baseline failed'))
        if not base.get('continuation'):
            base['phase'] = '最终网格五轮目标拟合'
            from batch_multiround import continue_job
            with server.RAW_LOCK:
                key, audit = continue_job(baseid, server, total_rounds=5)
            base.update(status='done', phase='正式父基准：五轮网格完成（叠加前）',
                result=dict(base['result'], grid_key=key), continuation=audit)
            save(source/'job.json', base)
        stop.set()
        thread.join()
        if resume:
            # Stack is short and restarts from the immutable five-round parent.
            # Preserve interrupted outputs for diagnosis; never train from a
            # partially overwritten stack recipe.
            names = [p for p in out.iterdir() if p.name not in ('job.json', 'interrupted_stack')]
            if names:
                archive = out/'interrupted_stack'/uuid.uuid4().hex
                archive.mkdir(parents=True)
                for p in names:
                    p.rename(archive/p.name)
        final['phase'] = '正式方案：三轮原生／网格／整数交替'
        save(out/'job.json', final)
        tracker = TrainingProgress(out/'training_progress.json', 3)
        with server.RAW_LOCK:
            train(out, source, final, tracker.update, SETTINGS)
        if not completed(identifier, final, server):
            raise RuntimeError('Final stack audit missing')
        final['phase'] = options.get('short_name', '') + '：五项叠加正式训练完成，BIN核验通过'
        tracker.update(stage='正式训练完成，BIN解码与CPU重放通过', state='done')
    except Exception as error:
        final.update(status='error', phase='正式训练失败，日志已保留', error=str(error), finished=time.time())
        (out/'error.log').write_text(traceback.format_exc(), encoding='utf-8')
        traceback.print_exc()
    finally:
        stop.set()
        thread.join()
        save(out/'job.json', {k:v for k,v in final.items() if k != 'process'})


class Handler(server.Handler):
    allowed_hosts = ()

    def trusted(self):
        return self.headers.get('Host') in self.allowed_hosts and self.headers.get('Origin') in (
            None, *('http://'+h for h in self.allowed_hosts))

    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path
        if not self.trusted():
            return self.respond(dict(error='Local origin required'), status=403)
        if path == '/api/formal-profile':
            return self.respond(dict(PROFILE, compute=gpu_runtime.policy()))
        bits = path.split('/')
        if len(bits) == 5 and bits[1:3] == ['api', 'jobs'] and bits[4] in ('stack-comparison', 'full-process'):
            if len(bits[3]) != 32 or any(c not in '0123456789abcdef' for c in bits[3]):
                return self.respond(dict(error='Invalid job'), status=400)
            folder = server.RUNS/bits[3]
            if bits[4] == 'full-process':
                import io, zipfile
                state = server.JOBS.get(bits[3], {})
                if state.get('status') not in ('done', 'error'):
                    return self.respond(dict(error='训练尚未完成'), status=409)
                memory = io.BytesIO()
                names = ('job.json', 'R5NATIVE.BIN', 'native_config.json', 'conversion_audit.json',
                    'input_audit.json', 'chart_target.json', 'fit/recipe.json', 'fit/fit_state.npz',
                    'fit.log', 'error.log', 'pc_compensation.json', 'grid_training.json',
                    'training_progress.json', 'grid_progress.json', 'stack_audit.json',
                    'stack_comparison.json', 'stack_progress.json')
                with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for source, prefix in ((folder, ''), (server.RUNS/state.get('base_job', 'missing'), 'baseline/')):
                        for name in names:
                            if (source/name).is_file():
                                archive.write(source/name, prefix+name)
                        for directory in ('stack_rounds', 'grid_4187_five_rounds', 'grid_distillation'):
                            for p in (source/directory).rglob('*'):
                                if p.is_file():
                                    archive.write(p, prefix+str(p.relative_to(source)).replace('\\', '/'))
                    archive.write(HERE/'formal_profile.json', 'formal_profile.json')
                    archive.write(HERE/'source-manifest.json', 'source-manifest.json')
                return self.respond(memory.getvalue(), 'application/zip', filename='formal-full-process.zip')
            result = folder/'stack_comparison.json'
            if not result.exists():
                return self.respond(dict(error='叠加报告尚未就绪'), status=409)
            return self.respond(result.read_bytes())
        return super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=4180)
    parser.add_argument('--lan-address', default='127.0.0.1')
    args = parser.parse_args()
    if not gpu_runtime.available():raise RuntimeError('Apple Metal/MPS is required for the formal profile')
    server.core.presets()
    server.RUNS.mkdir(exist_ok=True)
    (HERE/'batches').mkdir(exist_ok=True)
    for p in server.RUNS.glob('*/job.json'):
        state = json.loads(p.read_text())
        if state['status'] in ('running', 'queued'):
            state.update(status='error', phase='服务中断，可接续正式训练', error='Service interrupted')
            save(p, state)
        server.JOBS[state['id']] = state
    server.validate_fit = validate
    server.work = formal_work
    batch_training.completed_continuation = completed
    Handler.allowed_hosts = tuple(h+':'+str(args.port) for h in ('127.0.0.1', 'localhost', args.lan_address))
    print(json.dumps(dict(url='http://'+args.lan_address+':'+str(args.port), compute=gpu_runtime.policy()), ensure_ascii=False), flush=True)
    server.ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
