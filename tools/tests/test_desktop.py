"""CLI parity, completed-output publication, cancellation and key protection."""
import argparse
import json
import os
import queue
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataeater_builder.cli import build_parser
from dataeater_builder.desktop_model import TASKS, make_request
from dataeater_builder.desktop_jobs import Job
from dataeater_builder import packaging

class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'Synthetic guide.txt'
        self.input.write_text('Synthetic pressure is 380 bar. Stop the pump before inspection. ' * 10)

    def run_job(self, command, values, expected=0):
        job = Job(make_request(command, values), python=sys.executable)
        job.start()
        log = ''
        while True:
            event = job.events.get(timeout=15)
            if event[0] == 'done':
                self.assertEqual(event[1], expected, log)
                job.thread.join(timeout=3)
                self.assertFalse(job.thread.is_alive())
                self.assertFalse(list(self.root.glob('.dataeater-*')))
                return event, log
            log += event[1]

    def test_every_cli_option_and_command_has_a_form(self):
        parser = build_parser()
        subs = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        self.assertEqual(set(subs.choices), {t.command for t in TASKS})
        for task in TASKS:
            destinations = {a.dest.replace('_', '-') for a in subs.choices[task.command]._actions if a.dest != 'help'}
            self.assertEqual(destinations, {f.key for f in task.fields}, task.command)

    def test_build_review_inspect_and_legacy_review(self):
        database = self.root / 'my database.dataeater'
        _, log = self.run_job('build', {'input': str(self.input), 'output': str(database), 'name': 'Synthetic guide',
            'description': 'Test description', 'language': 'en', 'publisher': 'Synthetic publisher', 'license': 'CC0', 'target-chars': '500'})
        self.assertFalse(packaging.verify_database(str(database)))
        self.assertNotIn('.dataeater-', log)
        _, log = self.run_job('inspect', {'database': str(database)})
        self.assertIn('Synthetic guide', log)
        review = self.root / 'review'
        self.run_job('review', {'input': str(self.input), 'output': str(review), 'batch-chars': '1000'})
        reviewed = self.root / 'reviewed.dataeater'
        self.run_job('build-reviewed', {'input': str(review), 'output': str(reviewed), 'name': 'Checked guide'})
        self.assertFalse(packaging.verify_database(str(reviewed)))
        legacy = self.root / 'legacy'
        unused = self.root / 'unused.dataeater'
        self.run_job('build', {'input': str(self.input), 'output': str(unused), 'review': str(legacy)})
        self.assertTrue((legacy / 'LLM_PROMPT.txt').is_file())
        self.assertFalse(unused.exists())

    def test_encryption_key_reuse_and_device_licence(self):
        database = self.root / 'plain.dataeater'
        self.run_job('build', {'input': str(self.input), 'output': str(database)})
        key = self.root / 'creator.key'
        self.run_job('create-key', {'output': str(key)})
        _, public = packaging.read_creator_key_file(str(key))
        public_text = public
        locked = self.root / 'locked.dataeater'
        secret = self.root / 'private.secret'
        args = {'input': str(database), 'output': str(locked), 'secret': str(secret), 'creator-public-key': public_text,
            'creator': 'Synthetic creator', 'contact': 'Test contact'}
        self.run_job('encrypt', args)
        before = packaging.read_secret_file(str(secret))
        self.run_job('encrypt', args)
        self.assertEqual(before, packaging.read_secret_file(str(secret)))
        self.run_job('encrypt', dict(args, **{'force-new-key': True}))
        self.assertNotEqual(before, packaging.read_secret_file(str(secret)))
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        from cryptography.hazmat.primitives.asymmetric import ec
        device = ec.generate_private_key(ec.SECP256R1())
        request = packaging.make_request_code(device.public_key())
        licence = self.root / 'customer.lic'
        _, log = self.run_job('licence', {'database': str(locked), 'key': str(key), 'secret': str(secret),
            'request-code': request, 'expiry': '30d', 'output': str(licence)})
        self.assertTrue(licence.read_text().strip())
        self.assertIn('Unlock Code', log)
        self.run_job('licence', {'database': str(locked), 'key': str(key), 'secret': str(secret), 'request-code': request})

    def test_failed_operation_preserves_output(self):
        out = self.root / 'existing.dataeater'; out.write_text('Keep original bytes')
        wrong = self.root / 'bad.pdf'; wrong.write_text('Not a PDF')
        self.run_job('build', {'input': str(wrong), 'output': str(out)}, expected=1)
        self.assertEqual(out.read_text(), 'Keep original bytes')

    def test_validation_protects_inputs_keys_and_review_originals(self):
        key = self.root / 'creator.key'; key.write_text('private')
        examples = [('create-key', {'output': str(key)}),
            ('build', {'input': str(self.input), 'output': str(self.input)}),
            ('review', {'input': str(self.root), 'output': str(self.root / 'inside')}),
            ('review', {'input': str(self.input), 'output': str(self.root)}),
            ('build', {'input': str(self.input), 'output': str(self.root / 'out'), 'target-chars': '0'}),
            ('build', {'input': str(self.input), 'output': str(self.root / 'out'), 'target-chars': 'text'}),
            ('review', {'input': str(self.input), 'output': str(self.root / 'out'), 'batch-chars': '999'})]
        for command, values in examples:
            with self.assertRaises(ValueError, msg=command):
                make_request(command, values)
        request = make_request('create-key', {'output': str(key), 'force': True})
        self.assertIn('--force', request.args)

    def test_cancel_removes_partial_files_and_preserves_existing_output(self):
        out = self.root / 'existing.dataeater'; out.write_text('Original')
        worker = self.root / 'slow-python'
        worker.write_text('#!' + sys.executable + '\nimport sys,time\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index("--output")+1]);p.write_text("partial")\nprint("started",flush=True)\ntime.sleep(20)\n')
        worker.chmod(0o755)
        job = Job(make_request('build', {'input': str(self.input), 'output': str(out)}), python=str(worker))
        job.start()
        self.assertEqual(job.events.get(timeout=10)[0], 'line')
        self.assertTrue(job.cancel())
        event = job.events.get(timeout=6)
        self.assertEqual(event[:2], ('done', -1))
        job.thread.join(timeout=3)
        self.assertEqual(out.read_text(), 'Original')
        self.assertFalse(list(self.root.glob('.dataeater-*')))

    def test_two_output_failure_rolls_back_prior_replacement(self):
        database = self.root / 'plain.dataeater'
        self.run_job('build', {'input': str(self.input), 'output': str(database)})
        locked = self.root / 'locked.dataeater'; locked.write_text('Previous locked copy')
        secret = self.root / 'private.secret'
        actual_replace = os.replace
        def replace(source, dest):
            if Path(dest) == secret:
                raise PermissionError('Simulated second-output failure')
            return actual_replace(source, dest)
        with patch('dataeater_builder.desktop_jobs.os.replace', side_effect=replace):
            self.run_job('encrypt', {'input': str(database), 'output': str(locked), 'secret': str(secret)}, expected=1)
        self.assertEqual(locked.read_text(), 'Previous locked copy')
        self.assertFalse(secret.exists())

if __name__ == '__main__':
    unittest.main()
