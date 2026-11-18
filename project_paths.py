"""Lokasi data bersama untuk exporter dan bot, terlepas dari folder terminal."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
IMAGE_ROOT = ROOT / 'Gambar Ulasan PLN Mobile'
HTML_ROOT = IMAGE_ROOT / 'HTML'
EXPORT_ROOT = ROOT / 'Hasil Ekspor'
PART_SUFFIX = re.compile(r'\bPart\s+([1-9][0-9]*)\.html$', re.I)


def discover_sources():
    sources = {}
    for folder in (HTML_ROOT, IMAGE_ROOT, ROOT):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            match = PART_SUFFIX.search(path.name)
            if not match or not path.is_file():
                continue
            part = int(match[1])
            if part in sources and sources[part].parent == folder:
                raise ValueError(f'Ada lebih dari satu HTML Part {part} di {folder}. Sisakan satu sumber aktif untuk part ini.')
            sources.setdefault(part, path)
    return dict(sorted(sources.items()))


def image_name(number, username):
    safe_name = re.sub(r'[^\w -]', '', username)
    return f'{number:02d} - {safe_name}.png'


def image_for_review(part, number, username):
    name = image_name(number, username)
    canonical = IMAGE_ROOT / f'Part {part}' / name
    legacy = EXPORT_ROOT / f'Part {part}' / name
    return canonical if canonical.is_file() or not legacy.is_file() else legacy
