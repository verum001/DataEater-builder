"""Offline Linux desktop for DataEater Builder."""
import argparse
import queue
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from .desktop_model import TASKS, BY_COMMAND, make_request
from .desktop_jobs import Job
from .packaging import BUILDER_VERSION

BG = '#faf9f7'
SIDE = '#efeeeb'
INK = '#242424'
MUTED = '#62615e'
ACCENT = '#255e50'


def help_directory():
    source = Path(__file__).resolve().parents[2] / 'docs' / 'help'
    if source.is_dir():
        return source
    return Path(__file__).resolve().parents[3] / 'doc/dataeater-builder/docs/help'


class App:
    def __init__(self, root):
        self.root = root
        self.job = None
        self.outputs = []
        self.command = 'build'
        self.forms = {}
        self.vars = {}
        self.buttons = {}
        self.root.title('DataEater Builder')
        self.root.geometry('1100x800')
        self.root.minsize(760, 560)
        self.root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('sans-serif', 11), background=BG, foreground=INK)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('TEntry', fieldbackground='white', padding=8)
        style.configure('TButton', padding=(12, 8), background='#e9e7e2', borderwidth=0)
        style.map('TButton', background=[('active', '#dedbd4')])
        style.configure('Primary.TButton', background=ACCENT, foreground='white')
        style.map('Primary.TButton', background=[('disabled', '#a7b4af'), ('active', '#164738')])
        style.configure('TCheckbutton', background=BG)
        self.sidebar = tk.Frame(root, bg=SIDE, width=210)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text='DataEater', font=('sans-serif', 20, 'bold'), bg=SIDE, fg=INK).pack(anchor='w', padx=22, pady=(28, 0))
        tk.Label(self.sidebar, text='Builder  ' + BUILDER_VERSION, font=('sans-serif', 10), bg=SIDE, fg=MUTED).pack(anchor='w', padx=24, pady=(4, 30))
        for task in TASKS:
            button = tk.Button(self.sidebar, text=task.title, anchor='w', padx=14, pady=12,
                font=('sans-serif', 11), relief='flat', bd=0, bg=SIDE, fg=INK,
                activebackground='#dfddd7', command=lambda c=task.command: self.show_task(c))
            button.pack(fill='x', padx=12, pady=2)
            self.buttons[task.command] = button
        tk.Frame(self.sidebar, bg=SIDE).pack(fill='both', expand=True)
        tk.Button(self.sidebar, text='?  Help', anchor='w', padx=14, pady=12, bg=SIDE,
            relief='flat', font=('sans-serif', 11), command=self.show_help).pack(fill='x', padx=12, pady=(0, 22))
        main = ttk.Frame(root)
        main.pack(side='left', fill='both', expand=True, padx=32, pady=26)
        self.title = ttk.Label(main, font=('sans-serif', 23, 'bold'))
        self.title.pack(anchor='w')
        self.description = ttk.Label(main, style='Muted.TLabel', wraplength=660)
        self.description.pack(anchor='w', pady=(10, 20))
        viewport = ttk.Frame(main)
        viewport.pack(fill='both', expand=True)
        self.scroll = tk.Canvas(viewport, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(viewport, orient='vertical', command=self.scroll.yview)
        bar.pack(side='right', fill='y')
        self.scroll.pack(fill='both', expand=True, side='left')
        self.scroll.configure(yscrollcommand=bar.set)
        self.inner = ttk.Frame(self.scroll)
        self.window = self.scroll.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda e: self.scroll.configure(scrollregion=self.scroll.bbox('all')))
        self.scroll.bind('<Configure>', self.resize_form)
        self.root.bind_all('<Button-4>', lambda e: self.scroll.yview_scroll(-3, 'units') if self.in_form(e.widget) else None)
        self.root.bind_all('<Button-5>', lambda e: self.scroll.yview_scroll(3, 'units') if self.in_form(e.widget) else None)
        self.root.bind_all('<MouseWheel>', lambda e: self.scroll.yview_scroll(-int(e.delta / 120), 'units') if self.in_form(e.widget) else None)
        self.root.bind('<F1>', lambda e: self.show_help())
        self.root.bind('<Escape>', lambda e: self.cancel())
        for task in TASKS:
            self.create_form(task)
        actions = ttk.Frame(main)
        actions.pack(fill='x', pady=(16, 10))
        self.run_button = ttk.Button(actions, style='Primary.TButton', command=self.run)
        self.run_button.pack(side='left')
        self.cancel_button = ttk.Button(actions, text='Cancel', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=10)
        self.open_button = ttk.Button(actions, text='Open result folder', command=self.open_result, state='disabled')
        self.open_button.pack(side='right')
        self.progress = ttk.Progressbar(main, mode='indeterminate')
        self.progress.pack(fill='x', pady=(0, 8))
        self.status = ttk.Label(main, text='Ready. Your documents stay on this computer.', style='Muted.TLabel', wraplength=640)
        self.status.pack(anchor='w')
        detail = ttk.Frame(main)
        detail.pack(fill='x', pady=(8, 0))
        self.details_open = False
        ttk.Button(detail, text='Details', command=self.toggle_details).pack(side='left')
        ttk.Button(detail, text='Copy details', command=self.copy_details).pack(side='left', padx=8)
        self.log_frame = ttk.Frame(main)
        self.log = tk.Text(self.log_frame, height=7, wrap='word', bg='white', fg=INK,
            font=('monospace', 10), relief='flat', padx=12, pady=10, state='disabled')
        logbar = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=logbar.set)
        logbar.pack(side='right', fill='y')
        self.log.pack(fill='both', expand=True)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.show_task('build')
        self.root.after(80, self.poll)

    def in_form(self, widget):
        return str(widget).startswith(str(self.inner)) or widget is self.scroll

    def resize_form(self, event):
        self.scroll.itemconfigure(self.window, width=event.width)
        self.description.configure(wraplength=max(250, event.width - 10))
        for label in getattr(self, 'hint_labels', []):
            label.configure(wraplength=max(200, event.width - 30))

    def reveal(self, widget):
        top = widget.winfo_rooty() - self.inner.winfo_rooty()
        height = max(1, self.inner.winfo_height())
        visible_top = self.scroll.canvasy(0)
        visible_bottom = visible_top + self.scroll.winfo_height()
        if top < visible_top or top + widget.winfo_height() > visible_bottom:
            self.scroll.yview_moveto(max(0, top - 25) / height)

    def create_form(self, task):
        frame = ttk.Frame(self.inner)
        self.forms[task.command] = frame
        self.vars[task.command] = {}
        basic = ttk.Frame(frame)
        basic.pack(fill='x')
        advanced = ttk.Frame(frame)
        for field in task.fields:
            parent = advanced if field.advanced else basic
            variable = tk.BooleanVar(value=False) if field.kind == 'bool' else tk.StringVar(value=field.default)
            self.vars[task.command][field.key] = variable
            if field.kind == 'bool':
                ttk.Checkbutton(parent, text=field.label, variable=variable).pack(anchor='w', pady=(12, 0))
            else:
                ttk.Label(parent, text=field.label).pack(anchor='w', pady=(12, 5))
                row = ttk.Frame(parent)
                row.pack(fill='x')
                entry = ttk.Entry(row, textvariable=variable)
                entry.pack(side='left', fill='x', expand=True)
                entry.bind('<FocusIn>', lambda e: self.root.after_idle(lambda w=e.widget: self.reveal(w)))
                if field.kind == 'source':
                    ttk.Button(row, text='File…', command=lambda v=variable: self.choose(v, 'source')).pack(side='left', padx=(8, 0))
                    ttk.Button(row, text='Folder…', command=lambda v=variable: self.choose(v, 'folder')).pack(side='left', padx=(6, 0))
                elif field.kind in ('folder', 'database', 'key', 'secret', 'new_folder') or field.kind.startswith('save_'):
                    ttk.Button(row, text='Browse…', command=lambda v=variable, k=field.kind: self.choose(v, k)).pack(side='left', padx=(8, 0))
            if field.hint:
                hint = ttk.Label(parent, text=field.hint, style='Muted.TLabel', wraplength=600)
                hint.pack(anchor='w', pady=(4, 0))
                if not hasattr(self, 'hint_labels'):
                    self.hint_labels = []
                self.hint_labels.append(hint)
        if any(field.advanced for field in task.fields):
            def toggle():
                if advanced.winfo_manager():
                    advanced.pack_forget()
                    switch.configure(text='Advanced options ▸')
                else:
                    advanced.pack(fill='x', pady=(8, 0))
                    switch.configure(text='Advanced options ▾')
            switch = ttk.Button(frame, text='Advanced options ▸', command=toggle)
            switch.pack(anchor='w', pady=(18, 0))

    def show_task(self, command):
        if self.job:
            return
        for form in self.forms.values():
            form.pack_forget()
        self.command = command
        task = BY_COMMAND[command]
        self.title.configure(text=task.title)
        self.description.configure(text=task.description)
        self.forms[command].pack(fill='x')
        self.run_button.configure(text=task.action)
        for name, button in self.buttons.items():
            button.configure(bg='#dedcd6' if name == command else SIDE)
        self.scroll.yview_moveto(0)

    def choose(self, variable, kind):
        if kind == 'folder':
            path = filedialog.askdirectory(parent=self.root, title='Choose folder')
        elif kind == 'new_folder':
            path = filedialog.asksaveasfilename(parent=self.root, title='Choose a new review folder name', confirmoverwrite=False)
        elif kind.startswith('save_'):
            extension = {'save_db': '.dataeater', 'save_key': '.key', 'save_secret': '.secret', 'save_lic': '.lic'}[kind]
            path = filedialog.asksaveasfilename(parent=self.root, title='Save file', defaultextension=extension,
                filetypes=[('Output file', '*' + extension), ('All files', '*')], confirmoverwrite=False)
        else:
            types = {'source': [('Documents', '*.pdf *.txt *.md *.markdown')], 'database': [('DataEater databases', '*.dataeater')],
                'key': [('Signing keys', '*.key')], 'secret': [('Content keys', '*.secret')]}[kind]
            path = filedialog.askopenfilename(parent=self.root, filetypes=types + [('All files', '*')])
        if path:
            variable.set(path)

    def run(self):
        if self.job:
            return
        try:
            request = make_request(self.command, {k: v.get() for k, v in self.vars[self.command].items()})
        except ValueError as error:
            messagebox.showerror('Check your choices', str(error), parent=self.root)
            return
        existing = [str(path) for flag, path, directory in request.outputs if path.exists() and flag != 'secret']
        if existing and not messagebox.askyesno('Replace existing file?', 'These files will be replaced after a successful operation:\n\n' + '\n'.join(existing), parent=self.root):
            return
        if '--force' in request.args or '--force-new-key' in request.args:
            if not messagebox.askyesno('Replace private key?', 'Changing a key can break access to existing databases. Keep a secure backup of the old key. Continue?', parent=self.root):
                return
        if self.command == 'encrypt' and not self.vars['encrypt']['creator-public-key'].get().strip():
            if not messagebox.askyesno('No public signing key', 'The Android app needs your public signing key to verify access codes. Create a signing key first, or continue without one?', parent=self.root):
                return
        self.log.configure(state='normal'); self.log.delete('1.0', 'end'); self.log.configure(state='disabled')
        self.outputs = []
        self.open_button.configure(state='disabled')
        self.run_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        for button in self.buttons.values():
            button.configure(state='disabled')
        self.progress.start(12)
        self.status.configure(text='Working… You can cancel without replacing existing outputs.')
        self.job = Job(request)
        self.job.start()

    def poll(self):
        if self.job:
            try:
                while True:
                    event = self.job.events.get_nowait()
                    if event[0] == 'line':
                        self.log.configure(state='normal')
                        self.log.insert('end', event[1])
                        self.log.see('end')
                        self.log.configure(state='disabled')
                    else:
                        code = event[1]
                        self.outputs = event[2]
                        self.progress.stop()
                        self.progress.configure(value=0)
                        self.status.configure(text='Finished. Check Details for warnings.' if code == 0 else
                            'Cancelled. Existing outputs were preserved.' if code == -1 else 'Could not finish. Open Details for the reason and try again.')
                        if code != 0 and not self.details_open:
                            self.toggle_details()
                        if code == 0 and self.command in ('inspect', 'create-key', 'licence') and not self.details_open:
                            self.toggle_details()
                        self.run_button.configure(state='normal')
                        self.cancel_button.configure(state='disabled')
                        self.open_button.configure(state='normal' if self.outputs else 'disabled')
                        for button in self.buttons.values():
                            button.configure(state='normal')
                        self.job = None
                        break
            except queue.Empty:
                pass
        self.root.after(80, self.poll)

    def cancel(self):
        if self.job and self.job.cancel():
            self.status.configure(text='Cancelling…')
            self.cancel_button.configure(state='disabled')

    def toggle_details(self):
        self.details_open = not self.details_open
        if self.details_open:
            self.log_frame.pack(fill='both', pady=(8, 0))
        else:
            self.log_frame.pack_forget()

    def copy_details(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log.get('1.0', 'end-1c'))

    def open_result(self):
        if self.outputs:
            path = Path(self.outputs[0])
            try:
                subprocess.Popen(['xdg-open', str(path if path.is_dir() else path.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                messagebox.showinfo('Result folder', str(path.parent), parent=self.root)

    def show_help(self):
        window = tk.Toplevel(self.root)
        window.title('DataEater Builder — Help')
        window.geometry('940x700')
        window.minsize(650, 450)
        window.configure(bg=BG)
        help_path = help_directory()
        topics = sorted(help_path.glob('*.txt'))
        left = tk.Frame(window, bg=SIDE, width=240)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        tk.Label(left, text='Help', font=('sans-serif', 20, 'bold'), bg=SIDE).pack(anchor='w', padx=20, pady=24)
        body = ttk.Frame(window)
        body.pack(side='left', fill='both', expand=True, padx=24, pady=24)
        title = ttk.Label(body, font=('sans-serif', 20, 'bold'))
        title.pack(anchor='w', pady=(0, 18))
        bar = ttk.Scrollbar(body)
        bar.pack(side='right', fill='y')
        text = tk.Text(body, bg=BG, fg=INK, font=('sans-serif', 12), wrap='word', relief='flat', padx=4, pady=8, yscrollcommand=bar.set)
        text.pack(fill='both', expand=True)
        bar.configure(command=text.yview)
        def display(path):
            lines = path.read_text(encoding='utf-8').split('\n', 1)
            title.configure(text=lines[0])
            text.configure(state='normal'); text.delete('1.0', 'end'); text.insert('1.0', lines[1]); text.configure(state='disabled')
        for path in topics:
            label = path.read_text(encoding='utf-8').split('\n', 1)[0]
            tk.Button(left, text=label, anchor='w', wraplength=205, font=('sans-serif', 11),
                bg=SIDE, relief='flat', padx=16, pady=12, command=lambda p=path: display(p)).pack(fill='x')
        if topics:
            display(topics[0])
        else:
            title.configure(text='Help files not found')
            text.insert('1.0', 'See docs/GUI.md in the source project.')
        window.bind('<Escape>', lambda e: window.destroy())

    def close(self):
        if self.job:
            if messagebox.askyesno('Operation running', 'Cancel the operation before closing?', parent=self.root):
                self.cancel()
                self.root.after(100, self.close_when_idle)
            return
        self.root.destroy()

    def close_when_idle(self):
        if self.job:
            self.root.after(100, self.close_when_idle)
        else:
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description='DataEater Builder Linux desktop')
    parser.add_argument('--version', action='version', version=BUILDER_VERSION)
    parser.parse_args(argv)
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print('A Linux graphical session is required: ' + str(error))
        return 1
    App(root)
    root.mainloop()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
