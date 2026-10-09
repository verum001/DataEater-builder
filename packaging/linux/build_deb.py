#!/usr/bin/env python3
"""Build a source-only, architecture-independent Debian desktop package."""
import argparse
import gzip
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from dataeater_builder.packaging import BUILDER_VERSION


def build(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dataeater-deb-') as work:
        tree = Path(work)
        def put(relative, content, executable=False):
            path = tree / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            path.chmod(0o755 if executable else 0o644)
        package = tree / 'usr/share/dataeater-builder/tools/dataeater_builder'
        package.mkdir(parents=True)
        for source in (ROOT / 'tools/dataeater_builder').glob('*.py'):
            shutil.copy2(source, package / source.name)
        for name, module in [('dataeater-builder', 'cli'), ('dataeater-builder-gui', 'desktop')]:
            put('usr/bin/' + name, '#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / "share/dataeater-builder/tools"))\nfrom dataeater_builder.' + module + ' import main\nraise SystemExit(main())\n', True)
        doc = tree / 'usr/share/doc/dataeater-builder'
        doc.mkdir(parents=True)
        for name in ['README.md', 'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md']:
            shutil.copy2(ROOT / name, doc / name)
        shutil.copytree(ROOT / 'docs', doc / 'docs')
        shutil.copytree(ROOT / 'screenshots', doc / 'screenshots')
        (doc / 'copyright').write_text('Copyright 2026 Jack. Original code and documentation.\n\n' + (ROOT / 'LICENSE').read_text())
        with (doc / 'changelog.gz').open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as stream:
                stream.write((ROOT / 'CHANGELOG.md').read_bytes())
        put('usr/share/applications/dataeater-builder.desktop', (ROOT / 'packaging/linux/dataeater-builder.desktop').read_text())
        put('usr/share/icons/hicolor/scalable/apps/dataeater-builder.svg', (ROOT / 'assets/builder-icon.svg').read_text())
        installed_kb = sum(p.stat().st_size for p in (tree / 'usr').rglob('*') if p.is_file()) // 1024 + 1
        put('DEBIAN/control', f'''Package: dataeater-builder
Version: {BUILDER_VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: Jack
Installed-Size: {installed_kb}
Depends: python3 (>= 3.10), python3-tk, python3-pymupdf (>= 1.24), python3-cryptography (>= 42)
Recommends: xdg-utils
Description: Offline knowledge database builder with a Linux desktop
 Build, review, inspect, encrypt and licence DataEater databases.
 Includes a graphical interface, command line and offline help.
 PDF and encryption dependencies are supplied by the distribution.
''')
        for directory in tree.rglob('*'):
            if directory.is_dir():
                directory.chmod(0o755)
            elif 'usr/bin' not in str(directory):
                directory.chmod(0o644)
        destination = output / f'dataeater-builder_{BUILDER_VERSION}_all.deb'
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(tree), str(destination)], check=True)
        print(destination)
        return destination

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default=str(ROOT / 'dist'))
    build(parser.parse_args().output)
