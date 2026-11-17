"""Siapkan dan proses pilihan ulasan; gunakan --kirim untuk mengirim antrean."""
import argparse
import base64
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import random
import re
import shutil
import subprocess
import time

from siapkan_data_form import ROOT, load_reviews

FORM_URL = 'https://docs.google.com/forms/d/e/1FAIpQLScLEbK0oXWNpnBjDoinZXfTatIolDEQ9xcX9bWw-J5LdBCUMQ/viewform'
UNITS = ['Panakkukang', 'Mattoanging', 'Sungguminasa', 'Kalebajeng', 'Takalar', 'Malino']
PROGRESS_FILE = ROOT / 'progres_ulasan_form.json'
QUEUE_FILE = ROOT / 'antrean_ulasan_form.json'
STATUSES = {'disiapkan', 'diproses', 'siap_kirim', 'mengirim', 'terkirim', 'gagal', 'perlu_cek'}
UPLOAD_TIMEOUT = 120


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def select_reviews(reviews, part, numbers):
    available = {r['nomor'] for r in reviews if part == 'semua' or r['part'] == int(part)}
    selected = set()
    for token in numbers.split(','):
        match = re.fullmatch(r'\s*(\d+)\s*(?:-\s*(\d+)\s*)?', token)
        if not match:
            raise ValueError(f'Pilihan nomor tidak valid: {token!r}')
        start, end = int(match[1]), int(match[2] or match[1])
        if start < 1 or end < start or end > max(available):
            raise ValueError(f'Rentang di luar nomor tersedia: {token.strip()}')
        selected.update(range(start, end + 1))
    if selected - available:
        raise ValueError(f'Nomor tidak tersedia: {sorted(selected - available)}')
    return [dict(r) for r in reviews if (part == 'semua' or r['part'] == int(part)) and r['nomor'] in selected]


class Progress:
    def __init__(self, path=PROGRESS_FILE):
        self.path = path
        self.data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'versi': 1, 'ulasan': {}}
        if self.data.get('versi') != 1 or not isinstance(self.data.get('ulasan'), dict):
            raise ValueError('Format file progres tidak valid; jangan hapus riwayat pengiriman.')
        for entry in self.items.values():
            if entry.get('status') not in STATUSES:
                raise ValueError('Status pada file progres tidak dikenal.')

    @property
    def items(self):
        return self.data['ulasan']

    def save(self):
        write_json(self.path, self.data)

    def update(self, key, **changes):
        previous = dict(self.items[key])
        self.items[key].update(changes, diperbarui=datetime.now(timezone.utc).isoformat())
        try:
            self.save()
        except BaseException:
            self.items[key] = previous
            raise


def prepare_batch(selected, progress, queue_path=QUEUE_FILE):
    queue = []
    # Selesaikan validasi semua pilihan sebelum menyimpan progres atau membuka browser.
    for review in selected:
        image = ROOT / review['capture_ulasan']
        if not image.is_file() or not 0 < image.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError(f'Gambar hilang, kosong, atau melebihi 10 MB: {image}')
        content = image.read_bytes()
        identity = {key: value for key, value in review.items() if key != 'capture_ulasan'}
        signature = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode() + content).hexdigest()
        key = f'part-{review["part"]}/{review["nomor"]:02d}'
        old = progress.items.get(key)
        if old and old.get('signature') != signature:
            # Migrasi hash lama hanya jika isi data dan PNG masih persis sama.
            legacy_review = dict(review, capture_ulasan=old['foto'])
            legacy_signature = hashlib.sha256(json.dumps(legacy_review, sort_keys=True, ensure_ascii=False).encode() + content).hexdigest()
            if old.get('signature') != legacy_signature:
                raise ValueError(f'{key}: sumber berubah sejak dicatat. Periksa riwayat sebelum memproses ulang.')
        queue.append({'id': key, 'review': review, 'signature': signature,
                      'unit_up3': old['unit_up3'] if old else random.choice(UNITS)})
    for item in queue:
        key, review = item['id'], item['review']
        if key not in progress.items:
            progress.items[key] = {
                'status': 'disiapkan', 'foto': review['capture_ulasan'], 'username': review['username'],
                'signature': item['signature'], 'unit_up3': item['unit_up3'],
                'percobaan_proses': 0, 'percobaan_unggah': 0, 'error': None,
            }
        elif progress.items[key]['status'] == 'mengirim':
            progress.items[key].update(status='perlu_cek', error='Proses sebelumnya terhenti saat pengiriman. Periksa respons di Google Forms.')
        progress.items[key].update(signature=item['signature'], foto=review['capture_ulasan'])
    write_json(queue_path, {'disiapkan': datetime.now(timezone.utc).isoformat(), 'jumlah': len(queue), 'ulasan': queue})
    progress.save()
    return queue


class Browser:
    def __init__(self, session):
        command = shutil.which('agent-browser.cmd')
        if command:
            # Panggil binary langsung agar teks ulasan tidak diproses ulang oleh cmd.exe.
            command = str(Path(command).parent / 'node_modules/agent-browser/bin/agent-browser-win32-x64.exe')
        else:
            command = shutil.which('agent-browser')
        if not command or not Path(command).is_file():
            raise RuntimeError('Binary Agent Browser tidak ditemukan.')
        self.command, self.session = command, session

    def run(self, *args):
        result = subprocess.run(
            [self.command, '--session', self.session, '--json', *args],
            capture_output=True, text=True, encoding='utf-8', timeout=60,
        )
        try:
            response = json.loads(result.stdout)
        except ValueError:
            raise RuntimeError(result.stderr.strip() or 'Agent Browser tidak mengembalikan JSON.')
        if result.returncode or not response.get('success'):
            raise RuntimeError(str(response.get('error') or result.stderr.strip()))
        return response['data']

    def evaluate(self, code):
        encoded = base64.b64encode(code.encode()).decode()
        return self.run('eval', '-b', encoded)['result']

    def snapshot(self):
        return self.run('snapshot', '-i')

    def ref(self, role, name, prefix=False):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            refs = self.snapshot().get('refs', {})
            matches = [key for key, value in refs.items() if value['role'] == role
                       and (value['name'].startswith(name) if prefix else value['name'] == name)]
            if len(matches) == 1:
                return '@' + matches[0]
            time.sleep(0.2)
        raise RuntimeError(f'Elemen tidak ditemukan atau ambigu: {role} {name}')

    def click(self, role, name, prefix=False):
        deadline = time.monotonic() + 5
        while True:
            try:
                self.run('click', self.ref(role, name, prefix))
                return
            except RuntimeError as error:
                # Dropdown dapat masih menutupi tombol saat animasi penutup berjalan.
                if 'covered by' not in str(error) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)

    def dropdown(self, name, value):
        self.click('listbox', name, True)
        state = "document.querySelector('[role=listbox]').getAttribute('aria-expanded')"
        self.run('wait', '--fn', state + " === 'true'")
        self.click('option', value)
        self.run('wait', '--fn', state + " === 'false'")


def attachment_in_page(page, image):
    return image.name in page and 'button "Buka file"' in page


def image_attached(browser, image):
    return attachment_in_page(browser.run('snapshot')['snapshot'], image)


def upload_requests(browser):
    return browser.run('network', 'requests', '--filter', '/upload/drive/', '--method', 'POST').get('requests', [])


def completed_upload(browser, image, previous_ids):
    for request in reversed(upload_requests(browser)):
        if request['requestId'] in previous_ids:
            continue
        status = request.get('status')
        if status is not None and status >= 400:
            raise RuntimeError(f'Google Drive menolak unggahan (HTTP {status}).')
        if status != 200:
            continue
        detail = browser.run('network', 'request', request['requestId'])
        body = detail.get('responseBody')
        if not body:
            continue
        try:
            metadata = json.loads(body) if isinstance(body, str) else body
        except ValueError as error:
            raise RuntimeError('Respons unggah Google Drive tidak dapat dibaca sebagai metadata file.') from error
        if not isinstance(metadata, dict):
            raise RuntimeError('Respons unggah Google Drive tidak memuat metadata file.')
        if (metadata.get('title') == image.name and
                str(metadata.get('fileSize')) == str(image.stat().st_size) and metadata.get('id')):
            return metadata['id']
    return None


def insert_uploaded_file(browser, image, file_id):
    browser.click('tab', 'Terbaru')
    browser.click('radio', 'Tampilan Kisi')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        page = browser.snapshot()
        for key, ref in page.get('refs', {}).items():
            if ref.get('role') == 'option' and (ref['name'] == image.name or ref['name'].startswith(image.name + ' ')):
                # ID kartu tetap ada meskipun thumbnail baru belum tersedia.
                # Hint img pada snapshot hanya muncul setelah thumbnail dimuat.
                actual_id = browser.run('get', 'attr', '@' + key, 'data-id').get('value')
                if actual_id != file_id:
                    continue
                browser.run('click', '@' + key)
                browser.click('button', 'Sisipkan 1 item')
                browser.run('frame', 'main')
                return
        time.sleep(0.5)
    raise RuntimeError('File berhasil diunggah ke Drive, tetapi belum ditemukan pada tab Terbaru untuk disisipkan.')


def wait_for_attachment(browser, image, transfer, timeout=UPLOAD_TIMEOUT):
    deadline = time.monotonic() + timeout
    inserted = False
    announced = False
    while time.monotonic() < deadline:
        browser.run('frame', 'main')
        page = browser.run('snapshot')['snapshot']
        if attachment_in_page(page, image):
            return
        if not inserted:
            if not transfer['file_id']:
                transfer['file_id'] = completed_upload(browser, image, transfer['previous_ids'])
            if transfer['file_id']:
                print('  Unggahan selesai di Drive; memilih file lalu menekan Sisipkan.', flush=True)
                insert_uploaded_file(browser, image, transfer['file_id'])
                inserted = True
            elif 'progressbar' in page and not announced:
                print('  Google Drive masih mengunggah; menunggu hingga selesai.', flush=True)
                announced = True
        time.sleep(0.5)
    stage = 'pemasangan lampiran setelah Sisipkan' if inserted else 'penyelesaian unggahan Google Drive'
    raise RuntimeError(f'Timeout {timeout} detik saat menunggu {stage}.')


def upload_image(browser, image, on_attempt=lambda attempt: None):
    last_error = None
    transfer = {'file_id': None, 'previous_ids': set()}
    for attempt in range(1, 4):
        on_attempt(attempt)
        print(f'  Unggah {image.name}: percobaan {attempt}/3', flush=True)
        try:
            browser.run('frame', 'main')
            if image_attached(browser, image):
                return
            if transfer['file_id']:
                # Unggahan sudah selesai. Retry hanya pemilihan/penyisipan, tidak mengunggah salinan baru.
                wait_for_attachment(browser, image, transfer)
                return
            refs = browser.snapshot().get('refs', {}).values()
            if any(ref['role'] == 'dialog' for ref in refs):
                browser.click('button', 'Tutup pemilih Sisipkan file')
                browser.run('wait', '[role=dialog]', '--state', 'hidden')
            page = browser.run('snapshot')['snapshot']
            if 'button "Hapus file"' in page:
                browser.click('button', 'Hapus file')
            browser.click('button', 'CAPTURE ULASAN', True)
            # Input milik tombol Jelajah dipakai langsung tanpa dialog file Windows.
            browser.ref('button', 'Jelajah')
            browser.run('frame', browser.ref('Iframe', ''))
            browser.run('wait', 'input[type=file]', '--state', 'attached')
            transfer['previous_ids'] = {request['requestId'] for request in upload_requests(browser)}
            browser.run('upload', 'input[type=file]', str(image))
            browser.run('frame', 'main')
            wait_for_attachment(browser, image, transfer)
            return
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            last_error = error
            print(f'  Unggah gagal pada percobaan {attempt}/3: {error}', flush=True)
    raise RuntimeError(f'Gagal mengunggah setelah 3 percobaan: {last_error}') from last_error


def fill_review(browser, review, unit, on_upload=lambda attempt: None):
    browser.run('frame', 'main')
    browser.run('open', FORM_URL)
    for label, key in [('USERNAME (PEMBERI REVIEW)', 'username'),
                       ('Ulasan', 'ulasan'), ('Nama Petugas (PENGINPUT REVIEW)', 'nama_petugas')]:
        browser.run('fill', browser.ref('textbox', label, True), review[key])
    browser.dropdown('UNIT (USER UPLOAD)', review['unit'])
    browser.click('radio', str(review['rating']))
    browser.evaluate("""(() => {
        const el=document.querySelector('input[type=date]');
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el, DATE);
        el.dispatchEvent(new Event('input',{bubbles:true}));
        el.dispatchEvent(new Event('change',{bubbles:true}));
        el.blur();
    })()""".replace('DATE', json.dumps(review['tanggal_ulasan'])))

    image = ROOT / review['capture_ulasan']
    upload_image(browser, image, on_upload)

    actual = browser.evaluate("""({
        username:document.querySelector('input[name="entry.1399048517"]').value,
        unit:document.querySelector('input[name="entry.1577425024"]').value,
        rating:Number(document.querySelector('input[name="entry.1998011171"]').value),
        tanggal_ulasan:document.querySelector('input[type=date]').value,
        ulasan:document.querySelector('textarea').value,
        nama_petugas:document.querySelector('input[name="entry.1571464539"]').value
    })""")
    expected = {key: review[key] for key in actual}
    if actual != expected:
        raise RuntimeError('Data formulir berbeda dari sumber; berhenti sebelum Berikutnya.')
    browser.click('button', 'Berikutnya')
    browser.ref('listbox', 'UP3 MAKASSAR SELATAN', True)
    browser.dropdown('UP3 MAKASSAR SELATAN', unit)
    selected = browser.evaluate("document.querySelector('[role=option][aria-selected=true]').getAttribute('data-value')")
    if selected != unit:
        raise RuntimeError('Unit UP3 yang terpilih berbeda dari antrean.')
    browser.click('button', 'Berikutnya')
    browser.ref('button', 'Kirim')
    print(f'{review["username"]}: data lengkap, unit {unit}.', flush=True)


def process_batch(browser, queue, progress, send=False):
    failed = False
    for index, item in enumerate(queue, 1):
        key, review = item['id'], item['review']
        entry = progress.items[key]
        if entry['status'] == 'terkirim':
            print(f'[{index}/{len(queue)}] {key}: sudah terkirim, dilewati.', flush=True)
            continue
        if entry['status'] in {'mengirim', 'perlu_cek'}:
            print(f'{key}: hasil pengiriman belum pasti. Periksa Google Forms sebelum melanjutkan.', flush=True)
            return 1
        print(f'[{index}/{len(queue)}] {key}: {review["username"]}', flush=True)
        progress.update(key, status='diproses', error=None, percobaan_unggah=0,
                        percobaan_proses=entry['percobaan_proses'] + 1)
        submit_started = False
        try:
            fill_review(browser, review, item['unit_up3'],
                        on_upload=lambda attempt: progress.update(key, percobaan_unggah=attempt))
            progress.update(key, status='siap_kirim')
            if not send:
                print('Berhenti sebelum Kirim. Sisa antrean tersimpan; gunakan --kirim untuk batch penuh.', flush=True)
                return int(failed)
            submit_ref = browser.ref('button', 'Kirim')
            # Simpan sebelum klik; timeout setelah klik tidak boleh memicu pengiriman ulang.
            progress.update(key, status='mengirim')
            submit_started = True
            browser.run('click', submit_ref)
            confirmation = "['Jawaban Anda telah direkam.', 'Your response has been recorded.'].some(text => document.body.innerText.includes(text))"
            browser.run('wait', '--fn', confirmation)
            progress.update(key, status='terkirim', error=None, terkirim_pada=datetime.now(timezone.utc).isoformat())
            print(f'{key}: TERKIRIM (konfirmasi Google Forms diterima).', flush=True)
        except (Exception, KeyboardInterrupt) as error:
            uncertain = submit_started or progress.items[key]['status'] == 'mengirim'
            progress.update(key, status='perlu_cek' if uncertain else 'gagal',
                            error=str(error) or 'Proses dihentikan pengguna.')
            if isinstance(error, KeyboardInterrupt):
                raise
            print(f'{key}: {progress.items[key]["status"]}: {error}', flush=True)
            failed = True
            if uncertain:
                print('Batch dihentikan agar respons yang mungkin sudah terkirim tidak dikirim ulang.', flush=True)
                return 1
    return int(failed)


def confirm_status(queue, progress, delivered):
    if not delivered and any(progress.items[item['id']]['status'] == 'terkirim' for item in queue):
        raise ValueError('Entri terkirim tidak boleh direset menjadi belum terkirim.')
    for item in queue:
        progress.items[item['id']].update(
            status='terkirim' if delivered else 'gagal',
            error=None if delivered else 'Pengguna memastikan respons belum terkirim; boleh diproses ulang.',
            konfirmasi_manual=datetime.now(timezone.utc).isoformat(),
        )
    progress.save()


def show_reviews(reviews, progress):
    print('\n PART  FOTO  NAMA REVIEWER                     STATUS')
    print(' ' + '-' * 72)
    for review in reviews:
        key = f'part-{review["part"]}/{review["nomor"]:02d}'
        entry = progress.items.get(key, {})
        print(f' {review["part"]:>4}  {review["nomor"]:>4}  {review["username"]:<32}  {entry.get("status", "belum_diproses")}')
        if entry.get('error'):
            print(f'             Error: {entry["error"]}')


def choose_reviews(reviews, progress):
    while True:
        print('\nPILIH FOTO ULASAN')
        print('  1. Part 1\n  2. Part 2\n  3. Part 3 (anonim/parafrase)\n  4. Semua part\n  0. Keluar')
        part = input('Pilih part: ').strip()
        if part == '0':
            return None
        if part not in {'1', '2', '3', '4'}:
            print('Masukkan 1, 2, 3, 4, atau 0.')
            continue
        part = 'semua' if part == '4' else part
        available = [r for r in reviews if part == 'semua' or r['part'] == int(part)]
        show_reviews(available, progress)
        print('\nMasukkan nomor foto, misalnya: 2-7, 10-15, 18, 19-25')
        print('Ketik "semua" untuk memilih semua foto di part ini; 0 untuk kembali.')
        if part == 'semua':
            print('Nomor pilihan akan diterapkan pada SEMUA part.')
        while True:
            numbers = input('Nomor foto: ').strip()
            if numbers == '0':
                break
            if numbers.lower() == 'semua':
                numbers = ','.join(str(n) for n in sorted({r['nomor'] for r in available}))
            try:
                return select_reviews(reviews, part, numbers)
            except ValueError as error:
                print(f'Pilihan belum valid: {error}. Silakan masukkan lagi.')


def interactive():
    print('\n=== AUTOMASI ULASAN PLN MOBILE ===')
    print('Pilih foto di menu ini; tidak perlu mengetik perintah terminal.')
    reviews, progress = load_reviews(validate_images=False), Progress()
    missing = [r for r in reviews if not (ROOT / r['capture_ulasan']).is_file()]
    if missing:
        print(f'\n{len(missing)} gambar belum tersedia di Gambar Ulasan PLN Mobile/Part N.')
        print('  1. Buat gambar semua part dari HTML\n  2. Lanjut memilih gambar yang sudah ada\n  0. Keluar')
        while True:
            action = input('Pilih: ').strip()
            if action == '0':
                return 0
            if action == '1':
                from export_reviews import main as export_images
                export_images([])
                reviews = load_reviews()
                break
            if action == '2':
                break
            print('Masukkan 1, 2, atau 0.')
    while True:
        selected = choose_reviews(reviews, progress)
        if selected is None:
            print('Selesai. Progres yang sudah dicatat tetap tersimpan.')
            return 0
        try:
            queue = prepare_batch(selected, progress, QUEUE_FILE)
        except (ValueError, OSError) as error:
            print(f'Data belum dapat disiapkan: {error}')
            continue
        print(f'\nSeluruh data {len(queue)} foto pilihan sudah disiapkan dan disimpan.')
        show_reviews(selected, progress)
        while True:
            print('\nTINDAKAN UNTUK FOTO PILIHAN')
            print('  1. Jalankan batch: isi dan KIRIM semua pilihan')
            print('  2. Isi satu foto, berhenti sebelum Kirim')
            print('  3. Lihat status pilihan')
            print('  4. Catat hasil pengecekan manual')
            print('  5. Pilih foto lain\n  0. Keluar (antrean dan progres tetap tersimpan)')
            action = input('Pilih tindakan: ').strip()
            if action == '0':
                return 0
            if action == '5':
                break
            if action == '3':
                show_reviews(selected, progress)
                continue
            try:
                if action in {'1', '2'}:
                    # Seluruh data harus tersimpan sebelum koneksi browser dimulai.
                    queue = prepare_batch(selected, progress, QUEUE_FILE)
                    print('\nMenghubungkan Chrome. Pastikan sudah login Google dan Remote Debugging aktif')
                    print('di chrome://inspect/#remote-debugging. Pilih Allow jika Chrome memintanya.')
                    browser = Browser('pln-form')
                    browser.run('--auto-connect', 'tab', 'new', FORM_URL)
                    result = process_batch(browser, queue, progress, send=action == '1')
                    print('Proses selesai.' if result == 0 else 'Ada foto yang gagal/perlu dicek. Lihat status untuk rinciannya.')
                    show_reviews(selected, progress)
                elif action == '4':
                    print(f'Catatan ini berlaku untuk SELURUH {len(selected)} foto pilihan di atas.')
                    print('Pilih foto lain dahulu jika hanya ingin memperbarui sebagian nomor.')
                    print('  1. Sudah dipastikan TERKIRIM\n  2. Sudah dipastikan BELUM TERKIRIM\n  0. Batal')
                    confirmation = input('Hasil pengecekan: ').strip()
                    if confirmation in {'1', '2'}:
                        confirm_status(queue, progress, delivered=confirmation == '1')
                        show_reviews(selected, progress)
                    elif confirmation != '0':
                        print('Pilihan tidak dikenal; catatan tidak diubah.')
                else:
                    print('Pilihan tidak dikenal. Masukkan nomor menu.')
            except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                print(f'ERROR: {error}')
                print('Proses berhenti; periksa Chrome atau status foto sebelum melanjutkan.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--part', choices=('1', '2', '3', 'semua'), default='1')
    parser.add_argument('--nomor', default='1', help='Contoh: "2-7, 10-15, 18, 19-25"; nomor berulang diproses satu kali')
    parser.add_argument('--session', default='pln-form')
    parser.add_argument('--interaktif', action='store_true', help='Buka menu pemilihan foto dan tindakan')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--siapkan', '--cek', dest='prepare_only', action='store_true', help='Siapkan antrean tanpa membuka browser')
    mode.add_argument('--status', action='store_true', help='Lihat progres nomor pilihan tanpa membuka browser')
    mode.add_argument('--kirim', action='store_true', help='Isi dan kirim semua pilihan, lewati yang sudah terkirim')
    mode.add_argument('--konfirmasi', choices=('terkirim', 'belum_terkirim'), help='Catat hasil pengecekan manual; tidak membuka browser')
    args = parser.parse_args()
    try:
        if args.interaktif:
            return interactive()
        selected = select_reviews(load_reviews(validate_images=False), args.part, args.nomor)
        progress = Progress()
        if args.status:
            for review in selected:
                key = f'part-{review["part"]}/{review["nomor"]:02d}'
                entry = progress.items.get(key, {})
                print(f'{key} | {review["username"]} | {entry.get("status", "belum_diproses")} | {entry.get("error") or ""}')
            return 0
        queue = prepare_batch(selected, progress)
        print(f'{len(queue)} ulasan selesai disiapkan di {QUEUE_FILE.name}.', flush=True)
        if args.konfirmasi:
            confirm_status(queue, progress, args.konfirmasi == 'terkirim')
            print(f'Hasil pengecekan manual dicatat: {args.konfirmasi}.')
            return 0
        if args.prepare_only:
            return 0
        return process_batch(Browser(args.session), queue, progress, args.kirim)
    except (ValueError, OSError, RuntimeError, AssertionError, subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}', flush=True)
        return 1
    except KeyboardInterrupt:
        print('Dihentikan. Progres tersimpan.', flush=True)
        return 130
    except EOFError:
        print('\nInput ditutup. Progres yang sudah dicatat tetap tersimpan.')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
