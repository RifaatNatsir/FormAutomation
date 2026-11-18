"""Lokasi data bersama untuk exporter dan bot, terlepas dari folder terminal."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
IMAGE_ROOT = ROOT / 'Gambar Ulasan PLN Mobile'
HTML_ROOT = IMAGE_ROOT / 'HTML'
EXPORT_ROOT = ROOT / 'Hasil Ekspor'
PARTS = (1, 2, 3)


def source_for_part(part):
    for folder in (HTML_ROOT, IMAGE_ROOT, ROOT):
        matches = [path for path in folder.glob('*.html')
                   if re.search(rf'\bPart\s+{part}\.html$', path.name, re.I)]
        if len(matches) > 1:
            raise ValueError(f'Ada lebih dari satu HTML Part {part} di {folder}. Sisakan satu sumber aktif untuk part ini.')
        if matches:
            return matches[0]
    raise FileNotFoundError(f'Simpan HTML sumber dengan nama berakhiran Part {part}.html di {HTML_ROOT}')


def image_name(number, username):
    safe_name = re.sub(r'[^\w -]', '', username)
    return f'{number:02d} - {safe_name}.png'


def image_for_review(part, number, username):
    name = image_name(number, username)
    canonical = IMAGE_ROOT / f'Part {part}' / name
    legacy = EXPORT_ROOT / f'Part {part}' / name
    return canonical if canonical.is_file() or not legacy.is_file() else legacy
