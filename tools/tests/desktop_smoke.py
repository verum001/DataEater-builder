"""Linux graphical smoke test; only invented documents and temporary keys."""
import json
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataeater_builder.desktop import App, help_directory
from dataeater_builder.desktop_model import TASKS
from dataeater_builder import packaging

class DesktopSmoke(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.app = App(self.root)
        self.root.update()
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.input = self.folder / 'invented manual.txt'
        self.input.write_text('The invented PX-17 pump operates at 380 bar. Stop the pump before inspection. ' * 10)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.root.destroy)

    def operation(self, command, values):
        self.app.show_task(command)
        for key, value in values.items():
            self.app.vars[command][key].set(value)
        with patch('dataeater_builder.desktop.messagebox.askyesno', return_value=True), patch('dataeater_builder.desktop.messagebox.showerror') as error:
            self.app.run()
            error.assert_not_called()
        limit = time.monotonic() + 20
        while self.app.job and time.monotonic() < limit:
            self.root.update()
            time.sleep(.015)
        self.assertIsNone(self.app.job)
        self.assertTrue(self.app.status.cget('text').startswith('Finished'), self.app.log.get('1.0', 'end'))
        self.root.update()

    def test_all_seven_sidebar_tasks(self):
        database = self.folder / 'guide.dataeater'
        self.operation('build', {'input': str(self.input), 'output': str(database), 'name': 'Invented guide'})
        self.operation('inspect', {'database': str(database)})
        self.assertIn('Invented guide', self.app.log.get('1.0', 'end'))
        self.app.copy_details()
        self.assertIn('Invented guide', self.root.clipboard_get())
        review = self.folder / 'review'
        self.operation('review', {'input': str(self.input), 'output': str(review)})
        self.operation('build-reviewed', {'input': str(review), 'output': str(self.folder / 'checked.dataeater')})
        key = self.folder / 'creator.key'
        self.operation('create-key', {'output': str(key)})
        _, public = packaging.read_creator_key_file(str(key))
        locked = self.folder / 'locked.dataeater'
        self.operation('encrypt', {'input': str(database), 'output': str(locked), 'creator-public-key': public})
        from cryptography.hazmat.primitives.asymmetric import ec
        request = packaging.make_request_code(ec.generate_private_key(ec.SECP256R1()).public_key())
        licence = self.folder / 'customer.lic'
        self.operation('licence', {'database': str(locked), 'secret': str(locked.with_suffix('.secret')),
            'key': str(key), 'request-code': request, 'output': str(licence)})
        self.assertTrue(licence.is_file())
        self.assertFalse(list(self.folder.glob('.dataeater-*')))

    def test_help_and_minimum_window_scrolling(self):
        self.root.geometry('760x560'); self.root.update()
        for task in TASKS:
            self.app.show_task(task.command); self.root.update()
            self.assertGreater(self.app.scroll.winfo_height(), 20)
            for widget in self.app.forms[task.command].winfo_children():
                if hasattr(widget, 'cget'):
                    try:
                        if str(widget.cget('text')).startswith('Advanced options'):
                            widget.invoke()
                    except tk.TclError:
                        pass
            self.root.update()
            self.app.scroll.yview_moveto(1)
            self.root.update()
            self.assertGreaterEqual(self.app.scroll.yview()[1], .99)
        self.app.show_help();self.root.update()
        window = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        self.assertEqual(len(list(help_directory().glob('*.txt'))), 8)
        buttons = [w for frame in window.winfo_children() for w in frame.winfo_children() if isinstance(w, tk.Button)]
        self.assertEqual(len(buttons), 8)
        for button in buttons:
            button.invoke();self.root.update()
        window.destroy()

    def test_invalid_input_stays_in_form_and_reports_error(self):
        with patch('dataeater_builder.desktop.messagebox.showerror') as error:
            self.app.run()
            error.assert_called_once()
        self.assertIsNone(self.app.job)
        self.assertEqual(self.app.command, 'build')

if __name__ == '__main__':
    unittest.main()
