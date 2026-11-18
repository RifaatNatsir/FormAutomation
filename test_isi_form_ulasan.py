import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from isi_form_ulasan import (Progress, confirm_status, image_attached, load_reviews,
                             prepare_batch, process_batch, select_reviews, upload_image,
                             choose_reviews, interactive, completed_upload,
                             insert_uploaded_file, wait_for_attachment)


class SourceDiscoveryTests(unittest.TestCase):
    def test_filename_can_change_without_changing_part_number(self):
        import project_paths
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / 'Rekap Reviews PLN Mobile - 100 Ulasan Part 1.html'
            source.touch()
            with patch.object(project_paths, 'HTML_ROOT', root):
                self.assertEqual(project_paths.source_for_part(1), source)
                (root / 'Other Part 1.html').touch()
                with self.assertRaisesRegex(ValueError, 'lebih dari satu'):
                    project_paths.source_for_part(1)

    def test_new_markup_and_missing_other_parts(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'sample.html'
            source.write_text('<div class="rc"><div class="nm">Nama Tes</div><span class="st">' + '\u2605'*5 + '</span><span class="dt">18/11/26</span><div class="tx">Baris satu\n baris dua</div></div>', encoding='utf-8')
            with patch('siapkan_data_form.source_for_part', side_effect=[source, FileNotFoundError(), FileNotFoundError()]):
                reviews = load_reviews(validate_images=False)
            self.assertEqual(len(reviews), 1)
            self.assertEqual(reviews[0]['username'], 'Nama Tes')
            self.assertEqual(reviews[0]['ulasan'], 'Baris satu baris dua')
            self.assertEqual(reviews[0]['tanggal_ulasan'], '2026-11-18')


class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Batas fixture tetap 48 agar pengujian rentang tidak mengikuti ukuran data pengguna.
        cls.reviews = [r for r in load_reviews() if r['nomor'] <= 48]

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.progress = Progress(Path(self.directory.name) / 'progress.json')
        self.queue_file = Path(self.directory.name) / 'queue.json'

    def prepare(self, numbers='1-2'):
        return prepare_batch(select_reviews(self.reviews, '1', numbers), self.progress, self.queue_file)

    def test_range_selection_deduplicated_and_ordered(self):
        selected = select_reviews(self.reviews, '1', '2-7, 10-15, 18, 19-25, 18, 3')
        self.assertEqual([r['nomor'] for r in selected], list(range(2, 8)) + list(range(10, 16)) + [18] + list(range(19, 26)))
        self.assertEqual(len(select_reviews(self.reviews, 'semua', '1-2')), 6)

    def test_part_three_uses_matching_exported_images(self):
        from siapkan_data_form import ROOT
        selected = select_reviews(self.reviews, '3', '1-48')
        self.assertEqual(len(selected), 48)
        self.assertEqual(selected[0]['username'], next(r['username'] for r in self.reviews if r['part'] == 3))
        self.assertTrue(all((ROOT / r['capture_ulasan']).is_file() for r in selected))

    def test_invalid_ranges(self):
        for value in ('', '0', '2-1', '49', '1-49', '1,,2', '1,', 'abc', '-1', '1;2'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_reviews(self.reviews, '1', value)

    def test_all_data_saved_before_processing(self):
        queue = self.prepare()
        saved = json.loads(self.queue_file.read_text(encoding='utf-8'))
        self.assertEqual(saved['jumlah'], 2)
        self.assertEqual(saved['ulasan'][1]['review']['username'], self.reviews[1]['username'])
        self.assertTrue(all(self.progress.items[item['id']]['status'] == 'disiapkan' for item in queue))

    def test_invalid_image_prevents_partial_preparation(self):
        bad = dict(self.reviews[1], capture_ulasan='missing-file.png')
        with self.assertRaises(ValueError):
            prepare_batch([self.reviews[0], bad], self.progress, self.queue_file)
        self.assertEqual(self.progress.items, {})
        self.assertFalse(self.queue_file.exists())
        self.assertFalse(self.progress.path.exists())

    def test_source_change_gets_separate_history_and_original_stays_sent(self):
        original = self.prepare('1')
        self.progress.update(original[0]['id'], status='terkirim')
        changed = dict(self.reviews[0], ulasan='berubah')
        new = prepare_batch([changed], self.progress, self.queue_file)
        self.assertNotEqual(new[0]['id'], original[0]['id'])
        self.assertEqual(self.progress.items[new[0]['id']]['status'], 'disiapkan')
        self.assertEqual(self.progress.items[original[0]['id']]['status'], 'terkirim')
        self.progress.update(new[0]['id'], status='terkirim')
        repeated = prepare_batch([changed], self.progress, self.queue_file)
        self.assertEqual(repeated[0]['id'], new[0]['id'])
        self.assertEqual(self.progress.items[repeated[0]['id']]['status'], 'terkirim')
        restored = self.prepare('1')
        self.assertEqual(restored[0]['id'], original[0]['id'])
        self.assertEqual(self.progress.items[restored[0]['id']]['status'], 'terkirim')

    def test_legacy_path_migration_preserves_delivery_status(self):
        import hashlib
        from siapkan_data_form import ROOT
        review = dict(self.reviews[0])
        legacy_review = dict(review, capture_ulasan='Hasil Ekspor/Part 1/old.png')
        content = (ROOT / review['capture_ulasan']).read_bytes()
        signature = hashlib.sha256(json.dumps(legacy_review, sort_keys=True, ensure_ascii=False).encode() + content).hexdigest()
        self.progress.items['part-1/01'] = {'status': 'terkirim', 'signature': signature,
            'foto': legacy_review['capture_ulasan'], 'unit_up3': 'Malino'}
        queue = self.prepare('1')
        entry = self.progress.items['part-1/01']
        self.assertEqual(entry['status'], 'terkirim')
        self.assertEqual(entry['foto'], review['capture_ulasan'])
        self.assertNotEqual(entry['signature'], signature)
        self.assertEqual(queue[0]['unit_up3'], 'Malino')

    def test_reexported_image_does_not_reset_sent_status(self):
        original = self.prepare('1')
        self.progress.update(original[0]['id'], status='terkirim')
        image = Path(self.directory.name) / 'new-render.png'
        image.write_bytes(b'new image bytes')
        review = dict(self.reviews[0], capture_ulasan=str(image))
        repeated = prepare_batch([review], self.progress, self.queue_file)
        self.assertEqual(repeated[0]['id'], original[0]['id'])
        self.assertEqual(self.progress.items[repeated[0]['id']]['status'], 'terkirim')

    def test_corrupt_progress_is_not_silently_reset(self):
        self.progress.path.write_text('{invalid', encoding='utf-8')
        with self.assertRaises(ValueError):
            Progress(self.progress.path)

    def test_unit_is_stable_on_resume(self):
        first = self.prepare()
        second = self.prepare()
        self.assertEqual([r['unit_up3'] for r in first], [r['unit_up3'] for r in second])

    @patch('isi_form_ulasan.fill_review')
    def test_sent_skipped_and_each_remaining_record_confirmed(self, fill):
        queue = self.prepare('1-3')
        self.progress.update(queue[0]['id'], status='terkirim')
        browser = Mock()

        def command(*args):
            if args[0] == 'click':
                self.assertEqual(sum(e['status'] == 'mengirim' for e in self.progress.items.values()), 1)

        browser.run.side_effect = command
        self.assertEqual(process_batch(browser, queue, self.progress, send=True), 0)
        self.assertEqual(fill.call_count, 2)
        self.assertTrue(all(e['status'] == 'terkirim' for e in Progress(self.progress.path).items.values()))

    @patch('isi_form_ulasan.fill_review')
    def test_preview_preserves_remaining_queue(self, fill):
        queue = self.prepare()
        browser = Mock()
        self.assertEqual(process_batch(browser, queue, self.progress), 0)
        self.assertEqual(fill.call_count, 1)
        self.assertEqual(self.progress.items[queue[0]['id']]['status'], 'siap_kirim')
        self.assertEqual(self.progress.items[queue[1]['id']]['status'], 'disiapkan')
        browser.run.assert_not_called()

    @patch('isi_form_ulasan.fill_review', side_effect=[RuntimeError('upload gagal'), None])
    def test_fill_failure_recorded_and_batch_continues(self, fill):
        queue = self.prepare()
        self.assertEqual(process_batch(Mock(), queue, self.progress, send=True), 1)
        self.assertEqual(self.progress.items[queue[0]['id']]['status'], 'gagal')
        self.assertEqual(self.progress.items[queue[1]['id']]['status'], 'terkirim')
        self.assertIn('upload gagal', self.progress.items[queue[0]['id']]['error'])

    @patch('isi_form_ulasan.fill_review')
    def test_missing_confirmation_stops_without_resending(self, fill):
        queue = self.prepare()
        browser = Mock()
        browser.run.side_effect = [None, RuntimeError('konfirmasi timeout')]
        self.assertEqual(process_batch(browser, queue, self.progress, send=True), 1)
        self.assertEqual(self.progress.items[queue[0]['id']]['status'], 'perlu_cek')
        self.assertEqual(self.progress.items[queue[1]['id']]['status'], 'disiapkan')
        self.assertEqual(fill.call_count, 1)
        self.assertEqual(process_batch(browser, queue, self.progress, send=True), 1)
        self.assertEqual(fill.call_count, 1)

    def test_interrupted_send_requires_manual_check(self):
        queue = self.prepare('1')
        self.progress.update(queue[0]['id'], status='mengirim')
        queue = self.prepare('1')
        self.assertEqual(self.progress.items[queue[0]['id']]['status'], 'perlu_cek')
        confirm_status(queue, self.progress, delivered=False)
        self.assertEqual(self.progress.items[queue[0]['id']]['status'], 'gagal')
        confirm_status(queue, self.progress, delivered=True)
        with self.assertRaises(ValueError):
            confirm_status(queue, self.progress, delivered=False)

    @patch('isi_form_ulasan.fill_review')
    def test_failure_saving_delivery_confirmation_cannot_cause_resend(self, fill):
        queue = self.prepare()
        from isi_form_ulasan import write_json

        def fail_sent_save(path, data):
            if any(entry['status'] == 'terkirim' for entry in data['ulasan'].values()):
                raise OSError('gagal menyimpan status terkirim')
            write_json(path, data)

        with patch('isi_form_ulasan.write_json', side_effect=fail_sent_save):
            self.assertEqual(process_batch(Mock(), queue, self.progress, send=True), 1)
        self.assertEqual(Progress(self.progress.path).items[queue[0]['id']]['status'], 'perlu_cek')
        self.assertEqual(fill.call_count, 1)

    @patch('isi_form_ulasan.fill_review')
    def test_interrupt_after_send_is_uncertain(self, fill):
        queue = self.prepare('1')
        browser = Mock()
        browser.run.side_effect = [None, KeyboardInterrupt]
        with self.assertRaises(KeyboardInterrupt):
            process_batch(browser, queue, self.progress, send=True)
        self.assertEqual(Progress(self.progress.path).items[queue[0]['id']]['status'], 'perlu_cek')

    @patch('isi_form_ulasan.fill_review', side_effect=KeyboardInterrupt)
    def test_interrupt_keeps_status_on_disk(self, fill):
        queue = self.prepare('1')
        with self.assertRaises(KeyboardInterrupt):
            process_batch(Mock(), queue, self.progress, send=True)
        self.assertEqual(Progress(self.progress.path).items[queue[0]['id']]['status'], 'gagal')

    @patch('builtins.print')
    def test_interactive_selection_reprompts_after_invalid_input(self, output):
        with patch('builtins.input', side_effect=['9', '1', '2--7', '2-3,6']):
            selected = choose_reviews(self.reviews, self.progress)
        self.assertEqual([r['nomor'] for r in selected], [2, 3, 6])
        self.assertTrue(all(r['part'] == 1 for r in selected))

    @patch('builtins.print')
    def test_interactive_select_all_three_parts(self, output):
        with patch('isi_form_ulasan.load_reviews', return_value=self.reviews), patch('builtins.input', side_effect=['4', 'semua']):
            self.assertEqual(len(choose_reviews(self.reviews, self.progress)), 144)

    @patch('builtins.print')
    def test_interactive_select_part_three(self, output):
        with patch('builtins.input', side_effect=['3', '2-4']):
            selected = choose_reviews(self.reviews, self.progress)
        self.assertEqual([r['nomor'] for r in selected], [2, 3, 4])
        self.assertTrue(all(r['part'] == 3 for r in selected))

    @patch('builtins.print')
    @patch('export_reviews.main')
    @patch('isi_form_ulasan.load_reviews')
    def test_first_run_can_generate_missing_images(self, load, export, output):
        load.side_effect = [[dict(self.reviews[0], capture_ulasan='missing-first-run.png')], self.reviews]
        with patch('isi_form_ulasan.Progress', return_value=self.progress), \
             patch('builtins.input', side_effect=['1', '0']):
            self.assertEqual(interactive(), 0)
        export.assert_called_once_with([])

    @patch('builtins.print')
    @patch('isi_form_ulasan.Browser')
    def test_interactive_prepare_and_status_never_connect_browser(self, browser, output):
        with patch('isi_form_ulasan.Progress', return_value=self.progress), \
             patch('isi_form_ulasan.QUEUE_FILE', self.queue_file), \
             patch('builtins.input', side_effect=['1', '2-3', '3', '5', '0']):
            self.assertEqual(interactive(), 0)
        browser.assert_not_called()
        self.assertEqual(json.loads(self.queue_file.read_text())['jumlah'], 2)
        self.assertTrue(all(entry['status'] == 'disiapkan' for entry in self.progress.items.values()))

    @patch('builtins.print')
    @patch('isi_form_ulasan.process_batch', return_value=0)
    @patch('isi_form_ulasan.Browser')
    def test_interactive_saves_all_data_before_connecting_and_starting(self, browser, process, output):
        def connect(*args):
            self.assertEqual(json.loads(self.queue_file.read_text())['jumlah'], 2)
            self.assertEqual(len(Progress(self.progress.path).items), 2)
        browser.return_value.run.side_effect = connect
        with patch('isi_form_ulasan.Progress', return_value=self.progress), \
             patch('isi_form_ulasan.QUEUE_FILE', self.queue_file), \
             patch('builtins.input', side_effect=['2', '2-3', '1', '0']):
            self.assertEqual(interactive(), 0)
        browser.return_value.run.assert_called_once()
        self.assertEqual(browser.return_value.run.call_args.args[:3], ('--auto-connect', 'tab', 'new'))
        self.assertTrue(process.call_args.kwargs['send'])
        self.assertEqual([item['review']['nomor'] for item in process.call_args.args[1]], [2, 3])

    @patch('builtins.print')
    @patch('isi_form_ulasan.Browser')
    def test_interactive_manual_confirmation_without_browser(self, browser, output):
        with patch('isi_form_ulasan.Progress', return_value=self.progress), \
             patch('isi_form_ulasan.QUEUE_FILE', self.queue_file), \
             patch('builtins.input', side_effect=['1', '18', '4', '1', '0']):
            self.assertEqual(interactive(), 0)
        self.assertEqual(self.progress.items['part-1/18']['status'], 'terkirim')
        browser.assert_not_called()


class UploadTests(unittest.TestCase):
    @patch('isi_form_ulasan.image_attached', return_value=False)
    def test_browse_retried_exactly_three_times(self, attached):
        browser = Mock()
        browser.snapshot.return_value = {'refs': {}}
        browser.run.return_value = {'snapshot': ''}
        browser.ref.side_effect = RuntimeError('Jelajah belum siap')
        attempted = []
        with self.assertRaisesRegex(RuntimeError, '3 percobaan'):
            upload_image(browser, Path('foto.png'), attempted.append)
        self.assertEqual(attempted, [1, 2, 3])
        self.assertEqual(browser.ref.call_count, 3)

    @patch('isi_form_ulasan.upload_requests', return_value=[])
    @patch('isi_form_ulasan.wait_for_attachment')
    @patch('isi_form_ulasan.image_attached', return_value=False)
    def test_third_upload_succeeds_and_old_dialog_is_closed(self, attached, wait, requests):
        browser = Mock()
        browser.snapshot.return_value = {'refs': {'e1': {'role': 'dialog'}}}
        browser.run.return_value = {'snapshot': ''}
        browser.ref.side_effect = [RuntimeError('browse error'), RuntimeError('browse error'), '@browse', '@frame']
        attempted = []
        upload_image(browser, Path('foto.png'), attempted.append)
        self.assertEqual(attempted, [1, 2, 3])
        self.assertIn(unittest.mock.call('button', 'Tutup pemilih Sisipkan file'), browser.click.call_args_list)
        self.assertEqual(sum(call.args[0] == 'upload' for call in browser.run.call_args_list), 1)
        wait.assert_called_once()

    @patch('isi_form_ulasan.image_attached', side_effect=[False, True])
    def test_timeout_after_success_does_not_upload_twice(self, attached):
        browser = Mock()
        browser.snapshot.return_value = {'refs': {}}
        browser.run.return_value = {'snapshot': ''}
        browser.ref.side_effect = RuntimeError('timeout')
        upload_image(browser, Path('foto.png'))
        self.assertEqual(browser.ref.call_count, 1)

    def test_filename_only_is_not_attachment_confirmation(self):
        browser = Mock()
        browser.run.return_value = {'snapshot': 'foto.png'}
        self.assertFalse(image_attached(browser, Path('foto.png')))

    @patch('isi_form_ulasan.upload_requests')
    def test_upload_metadata_only_accepts_new_matching_file(self, requests):
        image = Mock(name='image')
        image.name = 'foto.png'
        image.stat.return_value.st_size = 100
        requests.return_value = [{'requestId': 'old', 'status': 200}, {'requestId': 'new', 'status': 200}]
        browser = Mock()
        browser.run.return_value = {'responseBody': json.dumps({'title': 'foto.png', 'fileSize': '100', 'id': 'correct-id'})}
        self.assertEqual(completed_upload(browser, image, {'old'}), 'correct-id')
        browser.run.assert_called_once_with('network', 'request', 'new')
        browser.run.return_value = {'responseBody': json.dumps({'title': 'other.png', 'fileSize': '100', 'id': 'wrong-id'})}
        self.assertIsNone(completed_upload(browser, image, {'old'}))

    def test_insert_chooses_uploaded_id_among_duplicate_names(self):
        browser = Mock()
        browser.snapshot.return_value = {
            'snapshot': '- option "foto.png Gambar" [ref=e1]\n- option "foto.png Gambar" [ref=e2]',
            'refs': {'e1': {'role': 'option', 'name': 'foto.png Gambar'}, 'e2': {'role': 'option', 'name': 'foto.png Gambar'}},
        }
        browser.run.side_effect = lambda *args: {'value': 'old-id' if args[2] == '@e1' else 'new-id'} if args[0] == 'get' else {}
        insert_uploaded_file(browser, Path('foto.png'), 'new-id')
        self.assertIn(unittest.mock.call('click', '@e2'), browser.run.call_args_list)
        self.assertNotIn(unittest.mock.call('click', '@e1'), browser.run.call_args_list)
        self.assertIn(unittest.mock.call('button', 'Sisipkan 1 item'), browser.click.call_args_list)
        self.assertIn(unittest.mock.call('get', 'attr', '@e2', 'data-id'), browser.run.call_args_list)

    @patch('isi_form_ulasan.time.sleep')
    @patch('isi_form_ulasan.insert_uploaded_file')
    @patch('isi_form_ulasan.completed_upload', side_effect=[None, 'new-id'])
    def test_completed_drive_upload_is_inserted_before_success(self, completed, insert, sleep):
        browser = Mock()
        snapshots = iter([
            {'snapshot': '- progressbar "Progres upload file": 50'},
            {'snapshot': '- button "Jelajah"'},
            {'snapshot': '- button "Buka file"\nfoto.png'},
        ])
        browser.run.side_effect = lambda *args: next(snapshots) if args[0] == 'snapshot' else {}
        transfer = {'file_id': None, 'previous_ids': set()}
        wait_for_attachment(browser, Path('foto.png'), transfer)
        insert.assert_called_once_with(browser, Path('foto.png'), 'new-id')
        self.assertEqual(transfer['file_id'], 'new-id')
        self.assertFalse(any(call.args[0] == 'upload' for call in browser.run.call_args_list))

    @patch('isi_form_ulasan.upload_requests', return_value=[])
    @patch('isi_form_ulasan.wait_for_attachment')
    @patch('isi_form_ulasan.image_attached', return_value=False)
    def test_insert_failure_retries_without_uploading_another_copy(self, attached, wait, requests):
        browser = Mock()
        browser.snapshot.return_value = {'refs': {}}
        browser.run.return_value = {'snapshot': ''}

        def pending_insert(browser, image, transfer):
            transfer['file_id'] = 'new-id'
            if wait.call_count == 1:
                raise RuntimeError('Sisipkan belum siap')

        wait.side_effect = pending_insert
        attempted = []
        upload_image(browser, Path('foto.png'), attempted.append)
        self.assertEqual(attempted, [1, 2])
        self.assertEqual(sum(call.args[0] == 'upload' for call in browser.run.call_args_list), 1)

    @patch('isi_form_ulasan.upload_requests', return_value=[{'requestId': 'new', 'status': 403}])
    def test_drive_rejection_reports_http_status(self, requests):
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
            completed_upload(Mock(), Path('foto.png'), set())


if __name__ == '__main__':
    unittest.main()
