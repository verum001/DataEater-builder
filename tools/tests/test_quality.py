"""Synthetic source coverage, review hints, confidentiality and atomic publishing."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataeater_builder import quality, packaging, extractors
from dataeater_builder.chunker import Page, chunk_pages
from dataeater_builder.cli import main
from dataeater_builder.review import export_review

class QualityTests(unittest.TestCase):
    def test_changes_do_not_claim_semantic_approval(self):
        old = '1. Do not remove PX-17 at 12.5 MPa.\n2. Check unit.'
        flags = quality.changes(old, '2. Do remove PX-18 at 13.5 bar.\n3. Check unit.')
        for name in ['numbers', 'restrictions', 'units', 'identifiers', 'numbered_steps']:
            self.assertIn(name + '_changed', flags)
        self.assertEqual(['text_changed'], quality.changes('1. Do not use 12.5 MPa.', '1.  Do not use 12.5  MPa.'))
        self.assertIn('restrictions_changed', quality.changes('Не снимать деталь.', 'Снимать деталь.'))
        self.assertEqual([], quality.changes('identical', 'identical'))

    def test_coverage_and_no_text_in_report(self):
        pages = [Page(1, 'The synthetic pump operates safely. ' * 7), Page(3, 'A' * 1301)]
        report = quality.source_report('s1', 'a' * 64, pages, 3, 'synthetic.pdf', [quality.metric(2, 'Short valid warning.', False, True)], chunks=chunk_pages(pages))
        self.assertFalse(report['pages'][1]['included'])
        self.assertEqual('below_100_characters', report['pages'][1]['reason'])
        self.assertEqual(20, report['pages'][1]['characters'])
        self.assertIn('pdf_layout_not_verified', report['pages'][0]['flags'])
        self.assertTrue(report['oversized_passages'])
        self.assertNotIn('synthetic pump', json.dumps(report))
        self.assertEqual('not_verified', report['technical_accuracy'])
        with self.assertRaises(ValueError):
            quality.source_report('s1', '', pages, 100000000, 'bad.pdf')

    def test_pdf_short_and_blank_pages_recorded_without_changing_filter(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'guide.pdf'; pdf = pymupdf.open()
            a = pdf.new_page(); a.insert_text((50, 50), 'Useful long paragraph. ' * 12)
            b = pdf.new_page(); b.insert_text((50, 50), 'Do not weld.')
            pdf.new_page(); pdf.save(p); pdf.close()
            doc = extractors.extract(str(p))
            self.assertEqual([1], [page.number for page in doc.pages])
            self.assertEqual([1, 2, 3], [m['page'] for m in doc.page_metrics])
            self.assertGreater(doc.page_metrics[1]['characters'], 0)
            self.assertEqual(0, doc.page_metrics[2]['characters'])

    def test_review_flags_embedded_and_encrypted_with_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp); source = r/'source.txt'; source.write_text('1. Do not remove PX-17 at 12.5 MPa. ' * 10)
            review = r/'review'; export_review(str(source), review)
            self.assertTrue((review/'quality_report.json').is_file())
            for f in (review/'reviewed').iterdir():
                f.write_text(f.read_text().replace('Do not', 'Do').replace('MPa', 'bar'))
            output = r/'reviewed.dataeater'
            self.assertEqual(0, main(['build-reviewed', str(review), '-o', str(output)]))
            manifest, data = packaging.read_package(str(output)); sources = json.loads(data['sources.json'])
            report = sources[0]['preparation_quality']; flags = report['pages'][0]['flags']
            self.assertIn('restrictions_changed', flags); self.assertIn('units_changed', flags)
            locked = r/'locked.dataeater'; key, _ = packaging.encrypt_database_file(str(output), str(locked))
            m, d = packaging.read_package(str(locked))
            self.assertNotIn(b'preparation_quality', locked.read_bytes())
            opened = packaging.decrypt_payload(packaging.EncryptedPayload(packaging._decode64(m['payload_nonce']), d['payload.enc']), key)
            self.assertIn('preparation_quality', opened['sources'])
            self.assertEqual([], packaging.verify_database(str(output)))

    def test_failed_publish_preserves_previous_database(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp)/'existing.dataeater'; dest.write_bytes(b'previous output')
            build = packaging.DatabaseBuild('test', 'Test', sources=[packaging.SourceRecord('s1', 'Synthetic')], chunks=chunk_pages([Page(1, 'Original text.')], source_id='s1'))
            with patch.object(packaging, 'verify_database', return_value=['synthetic verification failure']):
                with self.assertRaises(ValueError):
                    packaging.write_database(build, str(dest))
            self.assertEqual(b'previous output', dest.read_bytes())
            self.assertFalse(list(Path(temp).glob('.dataeater-build-*')))

if __name__ == '__main__': unittest.main()
