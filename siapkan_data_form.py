"""Pasangkan data HTML dengan PNG untuk pengisian formulir ulasan."""
from datetime import datetime
from html import unescape
import json
from pathlib import Path
import re

from project_paths import ROOT, PARTS, source_for_part, image_for_review


def load_reviews(validate_images=True):
    reviews = []
    for part in PARTS:
        try:
            source = source_for_part(part)
        except FileNotFoundError:
            continue
        cards = re.split(r'<div\s+class="(?:review-card|rc)"\s*>', source.read_text(encoding='utf-8'))[1:]
        if not cards:
            raise ValueError(f'Tidak ada kartu ulasan pada {source.name}')
        for number, card in enumerate(cards, 1):
            def field(css_class):
                match = re.search(r'class="(?:' + css_class + r')"[^>]*>(.*?)</', card, re.S)
                if not match:
                    raise ValueError(f'Part {part}, ulasan {number}: {css_class} tidak ditemukan')
                return ' '.join(unescape(match.group(1)).split())

            name = field('name|nm')
            image = image_for_review(part, number, name).relative_to(ROOT)
            rating = field('stars|st').count('★')
            date = datetime.strptime(field('date|dt'), '%d/%m/%y').date().isoformat()
            review = field('review-text|tx')
            assert name and review and 1 <= rating <= 5
            if validate_images:
                if not (ROOT / image).is_file():
                    raise FileNotFoundError(f'Gambar tidak ditemukan: {image}. Jalankan python export_reviews.py untuk membuat gambar dari HTML.')
                if not 0 < (ROOT / image).stat().st_size <= 10 * 1024 * 1024:
                    raise ValueError(f'Ukuran gambar harus 1 byte sampai 10 MB: {image}')
            reviews.append({
                'part': part,
                'nomor': number,
                'username': name,
                'unit': '1. MAKASSAR SELATAN',
                'capture_ulasan': image.as_posix(),
                'rating': rating,
                'tanggal_ulasan': date,
                'ulasan': review,
                'nama_petugas': 'H. T.',
            })
    if not reviews:
        raise FileNotFoundError('Tidak ada HTML sumber. Simpan file berakhiran Part 1.html, Part 2.html, atau Part 3.html di Gambar Ulasan PLN Mobile/HTML.')
    assert len({item['capture_ulasan'] for item in reviews}) == len(reviews)
    return reviews


if __name__ == '__main__':
    reviews = load_reviews()
    target = ROOT / 'data_ulasan_form.json'
    target.write_text(json.dumps(reviews, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(reviews)} pasangan data dan gambar tervalidasi: {target.name}')
    print(f'Pertama: {reviews[0]["username"]}, rating {reviews[0]["rating"]}, {reviews[0]["tanggal_ulasan"]}')
