"""Desktop forms mapped to the existing CLI; no separate database format."""
from dataclasses import dataclass
from pathlib import Path
from .cli import build_parser

@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = 'text'
    default: str = ''
    required: bool = False
    advanced: bool = False
    hint: str = ''

@dataclass(frozen=True)
class Task:
    command: str
    title: str
    description: str
    action: str
    fields: tuple

F = Field
METADATA = (
    F('description', 'Description', advanced=True),
    F('language', 'Language code', default='en', advanced=True, hint='For example: en, de, fr.'),
    F('license', 'Content licence', default='unknown', advanced=True, hint='Rights of the source material, not the app licence.'),
    F('publisher', 'Document publisher', advanced=True),
    F('target-chars', 'Passage size', 'number', '700', advanced=True, hint='Target characters per passage. Whole paragraphs may be longer.'),
)
TASKS = (
    Task('build', 'Build database', 'Choose documents, give the database a name, and save one file for your phone.', 'Build database', (
        F('input', 'Documents', 'source', required=True), F('name', 'Database name'),
        F('output', 'Save database', 'save_db', required=True), *METADATA,
        F('review', 'Export review instead', 'new_folder', advanced=True, hint='Optional legacy shortcut. Creates a review folder instead of a database.'))),
    Task('review', 'Prepare text review', 'Extract editable text and an LLM prompt. Nothing is sent online.', 'Prepare review', (
        F('input', 'Documents', 'source', required=True), F('output', 'New review folder', 'new_folder', required=True),
        F('batch-chars', 'Batch size', 'number', '30000', advanced=True, hint='Approximate characters per batch; whole PDF pages stay together.'))),
    Task('build-reviewed', 'Build reviewed text', 'Turn checked text into a database while preserving original page references.', 'Build database', (
        F('input', 'Review folder', 'folder', required=True), F('name', 'Database name'),
        F('output', 'Save database', 'save_db', required=True), *METADATA)),
    Task('inspect', 'Check database', 'Verify fingerprints and see documents, passages and extraction warnings.', 'Check database', (
        F('database', 'Database', 'database', required=True),)),
    Task('encrypt', 'Protect database', 'Create a locked copy and keep its content key in a private file.', 'Protect database', (
        F('input', 'Database', 'database', required=True), F('output', 'Save locked database', 'save_db', required=True),
        F('creator', 'Creator name'), F('contact', 'Contact'),
        F('creator-public-key', 'Creator public key', hint='Paste the public key shown by Create signing key.'),
        F('secret', 'Content key file', 'save_secret', advanced=True, hint='Blank: next to the locked database, ending in .secret. Existing keys are reused.'),
        F('force-new-key', 'Replace existing content key', 'bool', advanced=True, hint='Previously issued access codes will not unlock the new copy.'))),
    Task('create-key', 'Create signing key', 'Create your private signing key and a public key for locked databases.', 'Create signing key', (
        F('output', 'Private key file', 'save_key', 'creator.key', True),
        F('force', 'Replace existing signing key', 'bool', advanced=True, hint='Keep the old key to continue licensing databases signed with it.'))),
    Task('licence', 'Issue access code', 'Create an unlock code for the phone that sent you its request code.', 'Issue access code', (
        F('database', 'Locked database', 'database', required=True), F('request-code', 'Phone request code', required=True),
        F('secret', 'Content key file', 'secret', required=True), F('key', 'Private signing key', 'key', 'creator.key', True),
        F('output', 'Save access code (optional)', 'save_lic', hint='A file is easier to share. Blank: display the code in Details.'),
        F('expiry', 'Expiry', default='never', advanced=True, hint='never, 30d, 90d, 1y or YYYY-MM-DD.'))),
)
BY_COMMAND = {task.command: task for task in TASKS}

@dataclass(frozen=True)
class Request:
    command: str
    args: tuple
    outputs: tuple  # (CLI flag, resolved destination, is_directory)


def make_request(command, values):
    task = BY_COMMAND[command]
    args = [command]
    paths = {}
    clean = {}
    for field in task.fields:
        value = values.get(field.key, field.default)
        if field.kind == 'bool':
            if value:
                args.append('--' + field.key)
            clean[field.key] = bool(value)
            continue
        value = str(value).strip()
        clean[field.key] = value
        if field.required and not value:
            raise ValueError('Choose or enter ' + field.label.lower() + '.')
        if not value:
            continue
        if field.kind == 'number':
            minimum = 1000 if field.key == 'batch-chars' else 1
            try:
                number = int(value)
            except ValueError:
                raise ValueError(field.label + ' must be a whole number.') from None
            if number < minimum:
                raise ValueError(field.label + ' must be at least ' + str(minimum) + '.')
        if field.kind in ('source', 'folder', 'database', 'secret', 'key', 'new_folder') or field.kind.startswith('save_'):
            path = Path(value).expanduser().resolve()
            value = str(path)
            paths[field.key] = path
            if field.kind in ('source', 'folder', 'database', 'secret', 'key'):
                if not path.exists():
                    raise ValueError(field.label + ' does not exist.')
                if field.kind == 'folder' and not path.is_dir():
                    raise ValueError(field.label + ' must be a folder.')
                if field.kind in ('database', 'secret', 'key') and not path.is_file():
                    raise ValueError(field.label + ' must be a file.')
        if field.key in ('input', 'database'):
            args.append(value)
        else:
            args.extend(['--' + field.key, value])
    outputs = []
    if command == 'build' and clean.get('review'):
        outputs.append(('review', paths['review'], True))
    elif command != 'inspect' and 'output' in paths:
        outputs.append(('output', paths['output'], command == 'review'))
    if command == 'encrypt':
        secret = paths.get('secret', paths['output'].with_suffix('.secret'))
        outputs.append(('secret', secret, False))
        if 'secret' not in paths:
            args.extend(['--secret', str(secret)])
    destinations = [p for _, p, _ in outputs]
    if len(destinations) != len(set(destinations)):
        raise ValueError('Database and content key must have different filenames.')
    for flag, path, directory in outputs:
        if not path.parent.is_dir():
            raise ValueError('Choose an existing parent folder for ' + str(path) + '.')
        if directory and path.exists():
            raise ValueError('Choose a new review folder; existing reviews are never replaced.')
        if not directory and path.exists() and not path.is_file():
            raise ValueError('The destination must be a file: ' + str(path))
        for key, source in paths.items():
            if key in ('input', 'database', 'key') or (key == 'secret' and command != 'encrypt'):
                if path == source:
                    raise ValueError('The output must not replace an input or private signing key.')
                if directory and source.is_dir() and (source in path.parents or path in source.parents):
                    raise ValueError('Keep the review folder outside the document folder.')
    if command == 'create-key' and paths['output'].exists() and not clean.get('force'):
        raise ValueError('This signing key exists. Choose a new filename, or enable replacement in Advanced options.')
    # Preserve argparse as the authority for command grammar and defaults.
    try:
        build_parser().parse_args(args)
    except SystemExit:
        raise ValueError('One of the entered values is not valid for this command.') from None
    return Request(command, tuple(args), tuple(outputs))
