"""Round-trip a real PDF through editable batches; reject lost citations."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf
from dataeater_builder import cli, extractors
from dataeater_builder.review import export_review, import_review

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root/'manual.pdf'
        with pymupdf.open() as pdf:
            for text in ['The required test pressure is 380 bar at 850 rpm. ' * 9, '',
                         'Always isolate power before inspection. The limit is 12 volts. ' * 9]:
                page = pdf.new_page()
                if text:
                    page.insert_textbox(pymupdf.Rect(50,50,550,750),text,fontsize=11)
            pdf.set_metadata({'title':'Synthetic Maintenance Manual'})
            pdf.save(self.pdf)
        self.review = self.root/'review'
        export_review(str(self.pdf), str(self.review), batch_chars=1000)
        self.parts = sorted((self.review/'reviewed').glob('*.txt'))

    def test_round_trip_keeps_skipped_page_numbers_and_facts(self):
        sources = import_review(self.review)
        self.assertEqual([p.number for p in sources[0][1]], [1,3])
        self.assertTrue((self.review/'LLM_PROMPT.txt').exists())
        self.assertIn('Do not summarize', (self.review/'LLM_PROMPT.txt').read_text())
        self.parts[0].write_text(self.parts[0].read_text().replace('required test pressure','specified test pressure'))
        dest = self.root/'manual.dataeater'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['build-reviewed',str(self.review),'-o',str(dest),'--name','My Aviation Database']),0)
        with zipfile.ZipFile(dest) as z:
            self.assertEqual(json.loads(z.read('manifest.json'))['name'],'My Aviation Database')
            chunks = [json.loads(l) for l in z.read('chunks.jsonl').decode().splitlines()]
            self.assertEqual({c['page'] for c in chunks},{1,3})
            self.assertTrue(any('380 bar' in c['text'] for c in chunks))
            self.assertEqual(json.loads(z.read('sources.json'))[0]['title'],'Synthetic Maintenance Manual')

    def test_final_chunk_ids_are_unique_across_documents(self):
        from dataeater_builder import packaging
        from dataeater_builder.chunker import Chunk
        build=packaging.DatabaseBuild(database_id="test",name="Test",
              sources=[packaging.SourceRecord("s1","First"),packaging.SourceRecord("s2","Second")],
              chunks=[Chunk(text="First document text",page_start=1,page_end=1,source_id="s1",chunk_id="c003"),
                      Chunk(text="Second document text",page_start=3,page_end=3,source_id="s2",chunk_id="c003")])
        dest=self.root/"unique.dataeater"
        packaging.write_database(build,str(dest))
        self.assertEqual(packaging.verify_database(str(dest)),[])
        with zipfile.ZipFile(dest) as z:
            chunks=[json.loads(l) for l in z.read("chunks.jsonl").decode().splitlines()]
            self.assertEqual([c["id"] for c in chunks],["c001","c002"])

    def test_publisher_structure_survives_review_and_database(self):
        pdf_path=self.root/'structured.pdf'
        with pymupdf.open() as pdf:
            for title in ['Four-Stroke Cycle','Intake Stroke']:
                page=pdf.new_page()
                page.insert_textbox(pymupdf.Rect(50,50,550,750),title+"\n"+"The test piston moves downward. "*20,fontsize=11)
            pdf.set_toc([[1,'Four-Stroke Cycle',1],[2,'Intake Stroke',2]])
            pdf.save(pdf_path)
        folder=self.root/'structured-review'
        export_review(str(pdf_path),str(folder))
        pages=import_review(folder)[0][1]
        self.assertEqual('Four-Stroke Cycle > Intake Stroke',pages[1].section_paths['Intake Stroke'])
        dest=self.root/'structured.dataeater'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['build-reviewed',str(folder),'-o',str(dest)]),0)
        with zipfile.ZipFile(dest) as z:
            chunks=[json.loads(l) for l in z.read('chunks.jsonl').decode().splitlines()]
            selected=[c for c in chunks if c['page']==2]
            self.assertTrue(any(c.get('search_context')=='Four-Stroke Cycle > Intake Stroke' for c in selected))
            self.assertTrue(all(' > ' not in c['text'] for c in selected))
        manifest=json.loads((folder/'review.json').read_text())
        manifest['documents'][0]['page_contexts']['2']['paths']={'Intake Stroke':{}}
        (folder/'review.json').write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):import_review(folder)

    def test_modified_original_is_rejected(self):
        original = next((self.review/'original').glob('*.txt'))
        original.write_text(original.read_text()+'changed')
        with self.assertRaisesRegex(ValueError,'Original batch was modified'):import_review(self.review)

    def test_changed_page_marker_is_rejected(self):
        self.parts[0].write_text(self.parts[0].read_text().replace('PAGE 1','PAGE 2'))
        with self.assertRaisesRegex(ValueError,'page marker'):import_review(self.review)

    def test_missing_batch_is_rejected(self):
        self.parts[0].unlink()
        with self.assertRaises(FileNotFoundError):import_review(self.review)

    def test_empty_reviewed_page_is_rejected(self):
        self.parts[0].write_text('=== PAGE 1 ===\n')
        with self.assertRaisesRegex(ValueError,'empty'):import_review(self.review)

    def test_commentary_is_rejected(self):
        self.parts[0].write_text('Here is the corrected text:\n'+self.parts[0].read_text())
        with self.assertRaisesRegex(ValueError,'commentary'):import_review(self.review)

    def test_export_never_overwrites_edits(self):
        with self.assertRaisesRegex(ValueError,'already exists'):export_review(str(self.pdf),str(self.review))

    def test_legacy_text_page_markers_are_preserved(self):
        doc = extractors.extract_txt(str(self.parts[-1]))
        self.assertEqual([p.number for p in doc.pages],[3])

    def test_manifest_path_traversal_is_rejected(self):
        f = self.review/'review.json';manifest=json.loads(f.read_text())
        manifest['documents'][0]['parts'][0]['filename']='../outside.txt'
        f.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'filename'):import_review(self.review)

    def test_scanned_pdf_fails_without_partial_export(self):
        path=self.root/'scan.pdf'
        with pymupdf.open() as pdf:
            pdf.new_page();pdf.save(path)
        folder=self.root/'scan-review'
        with self.assertRaises(ValueError):export_review(str(path),str(folder))
        self.assertFalse(folder.exists())

if __name__ == '__main__':unittest.main()
