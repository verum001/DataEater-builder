"""Run a CLI child process and publish only completed outputs."""
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path

class Job:
    def __init__(self, request, python=None):
        self.request = request
        candidate = Path(__file__).resolve().parent.parent / '.venv/bin/python3'
        self.python = python or (str(candidate) if candidate.exists() else sys.executable)
        self.events = queue.Queue()
        self.cancelled = threading.Event()
        self.process = None
        self.lock = threading.Lock()
        self.thread = None
        self.committing = False

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def cancel(self):
        with self.lock:
            if self.committing:
                return False
            self.cancelled.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()
                threading.Thread(target=self._kill_later, args=(self.process,), daemon=True).start()
        return True

    @staticmethod
    def _kill_later(process):
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def _run(self):
        try:
            self._execute()
        except Exception as error:
            self.events.put(('line', 'Could not complete operation: ' + str(error) + '\n'))
            self.events.put(('done', 1, []))

    def _execute(self):
        with ExitStack() as cleanup:
            args = list(self.request.args)
            staged = []
            for flag, destination, directory in self.request.outputs:
                temp = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix='.dataeater-', dir=destination.parent)))
                os.chmod(temp, 0o700)
                output = temp / destination.name
                if flag == 'secret' and destination.exists() and '--force-new-key' not in args:
                    shutil.copy2(destination, output)
                index = args.index('--' + flag)
                args[index + 1] = str(output)
                staged.append((output, destination, directory))
            env = os.environ.copy()
            tools = str(Path(__file__).resolve().parent.parent)
            env['PYTHONPATH'] = tools + os.pathsep + env.get('PYTHONPATH', '')
            env['PYTHONUNBUFFERED'] = '1'
            with self.lock:
                if self.cancelled.is_set():
                    self.events.put(('done', -1, []))
                    return
                self.process = subprocess.Popen([self.python, '-u', '-m', 'dataeater_builder', *args],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding='utf-8', errors='replace', env=env)
            with self.process.stdout:
                for line in self.process.stdout:
                    for source, destination, _ in staged:
                        line = line.replace(str(source), str(destination))
                    self.events.put(('line', line))
            code = self.process.wait()
            if self.cancelled.is_set():
                self.events.put(('done', -1, []))
                return
            if code:
                self.events.put(('done', code, []))
                return
            for source, destination, directory in staged:
                if not source.exists():
                    raise RuntimeError('The command did not create ' + destination.name)
            with self.lock:
                if self.cancelled.is_set():
                    self.events.put(('done', -1, []))
                    return
                self.committing = True
            # Retain originals until all destinations have been published. Roll back
            # any prior replacements if a later move fails (e.g. permissions).
            replaced = []
            try:
                for source, destination, directory in staged:
                    backup = source.parent / 'previous-output'
                    existed = destination.exists()
                    if existed:
                        shutil.copy2(destination, backup)
                    os.replace(source, destination)
                    replaced.append((destination, backup if existed else None, directory))
            except Exception:
                for destination, backup, directory in reversed(replaced):
                    if backup:
                        os.replace(backup, destination)
                    elif directory:
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                raise
            self.events.put(('done', 0, [str(p) for _, p, _ in staged]))
