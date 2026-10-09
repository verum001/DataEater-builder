#!/usr/bin/env python3
"""Prepare a local release folder; never publish or include user documents."""
import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from dataeater_builder.packaging import BUILDER_VERSION


def source_files():
    for name in ['.gitignore', 'README.md', 'CHANGELOG.md', 'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'pyproject.toml',
                 'tools/dataeater-builder', 'tools/dataeater-builder-gui', 'tools/requirements.txt']:
        yield ROOT / name
    for directory, pattern in [('tools/dataeater_builder', '*.py'), ('tools/tests', '*.py'), ('docs', '*.md'),
                              ('docs/help', '*.txt'), ('packaging/linux', '*.py'), ('packaging/linux', '*.desktop'),
                              ('assets', '*.svg'), ('screenshots', '*.png')]:
        yield from sorted((ROOT / directory).glob(pattern))


def prepare(output, validation=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / 'packaging/linux/build_deb.py'), '--output', str(output)], check=True)
    archive = output / f'DataEater-Builder-{BUILDER_VERSION}-source.zip'
    paths = sorted(set(source_files()))
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise ValueError('Unexpected missing or symlinked release input: ' + str(path))
            bundle.write(path, str(Path(f'DataEater-Builder-{BUILDER_VERSION}') / path.relative_to(ROOT)))
    shutil.copy2(ROOT / f'docs/RELEASE_NOTES_{BUILDER_VERSION}.md', output / 'RELEASE_NOTES.md')
    shutil.copy2(ROOT / 'docs/PUBLISHING.md', output / 'UPLOAD_INSTRUCTIONS.md')
    if validation:
        shutil.copy2(validation, output / 'VALIDATION.md')
    else:
        (output / 'VALIDATION.md').write_text('Validation has not been recorded for this build. Run the documented tests and replace this file before publishing.\n')
    checksummed = [p for p in output.iterdir() if p.is_file() and p.name != 'SHA256SUMS']
    (output / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in sorted(checksummed)))
    print(f'{len(paths)} source files. Release prepared in {output}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'dist' / ('v' + BUILDER_VERSION)))
    parser.add_argument('--validation', help='Markdown report containing results from this build')
    args = parser.parse_args()
    prepare(args.output, args.validation)
