"""Lokasi data bersama untuk exporter dan bot, terlepas dari folder terminal."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
IMAGE_ROOT = ROOT / 'Gambar Ulasan PLN Mobile'
HTML_ROOT = IMAGE_ROOT / 'HTML'
EXPORT_ROOT = ROOT / 'Hasil Ekspor'
PARTS = (1, 2, 3)


def source_for_part(part):
    count = 48 if part == 3 else 50
    name = f'Rekap Google Reviews PLN Mobile - {count} Ulasan Part {part}.html'
    for folder in (HTML_ROOT, IMAGE_ROOT, ROOT):
        if (folder / name).is_file():
            return folder / name
    raise FileNotFoundError(f'Simpan HTML sumber di {HTML_ROOT / name}')


def image_name(number, username):
    safe_name = re.sub(r'[^\w -]', '', username)
    return f'{number:02d} - {safe_name}.png'


def image_for_review(part, number, username):
    name = image_name(number, username)
    canonical = IMAGE_ROOT / f'Part {part}' / name
    legacy = EXPORT_ROOT / f'Part {part}' / name
    return canonical if canonical.is_file() or not legacy.is_file() else legacy
