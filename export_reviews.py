"""Ekspor setiap kartu ulasan HTML ke PNG, lalu kemas sebagai ZIP."""
from pathlib import Path
import argparse
import re
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image
from playwright.sync_api import sync_playwright
from playwright.sync_api import Error as PlaywrightError
from project_paths import ROOT, IMAGE_ROOT, EXPORT_ROOT, PARTS, source_for_part, image_name

OUTPUT = IMAGE_ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', type=Path, help='File HTML tertentu yang ingin diekspor')
    parser.add_argument('--output', type=Path, help='Folder hasil untuk satu file HTML')
    args = parser.parse_args(argv)
    if args.output and not args.file:
        parser.error('--output harus disertai file HTML.')
    if args.file:
        source = args.file.resolve()
        part = re.search(r'Part (\d+)$', source.stem)
        default_folder = IMAGE_ROOT / f'Part {part[1]}' if part else EXPORT_ROOT / source.stem
        folder = (args.output or default_folder).resolve()
        jobs = [(source, folder)]
        archive = folder.parent / (folder.name + '.zip') if args.output else EXPORT_ROOT / (folder.name + '.zip')
        archive_root = folder
    else:
        jobs = []
        for part in PARTS:
            try:
                jobs.append((source_for_part(part), OUTPUT / f'Part {part}'))
            except FileNotFoundError:
                continue
        if not jobs:
            parser.error('Tidak ada HTML sumber di Gambar Ulasan PLN Mobile/HTML.')
        archive = EXPORT_ROOT / 'Gambar Ulasan PLN Mobile.zip'
        archive_root = OUTPUT
    for source, _ in jobs:
        if not source.is_file():
            parser.error(f'File tidak ditemukan: {source}')
    files = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='msedge', headless=True)
        except PlaywrightError:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 800, 'height': 900}, device_scale_factor=2)
        for source, folder in jobs:
            folder.mkdir(parents=True, exist_ok=True)
            page.goto(source.as_uri())
            page.evaluate('document.fonts.ready')
            cards = page.locator('.review-card, .rc')
            expected = len(re.findall(r'<div\s+class="(?:review-card|rc)"\s*>', source.read_text(encoding='utf-8')))
            assert cards.count() == expected and expected > 0
            for index in range(cards.count()):
                card = cards.nth(index)
                name = card.locator('.name, .nm').inner_text().strip()
                assert card.locator('.review-text, .tx').inner_text().strip()
                target = folder / image_name(index + 1, name)
                card.screenshot(path=str(target), animations='disabled')
                with Image.open(target) as img:
                    assert img.width == 1000 and img.height > 100
                    img.verify()
                files.append(target)
            print(f'{source.name}: {expected} PNG berhasil dibuat di {folder}', flush=True)
        browser.close()
    archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive, 'w', ZIP_DEFLATED) as z:
        for file in files:
            z.write(file, file.relative_to(archive_root))
    with ZipFile(archive) as z:
        assert len(z.namelist()) == len(files) and z.testzip() is None
    print(f'Selesai: {len(files)} gambar; ZIP: {archive}', flush=True)


if __name__ == '__main__':
    main()
