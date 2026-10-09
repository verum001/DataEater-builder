import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dataeater_builder.chunker import *

class Preservation(unittest.TestCase):
    def test_short_heading_body_is_preserved(self):
        chunks=chunk_pages([Page(3,"FUEL FILTER\nReplace every 12 months. Never clean with compressed air.")])
        self.assertIn("Never clean", " ".join(c.text for c in chunks))
    def test_numeric_value_is_not_a_heading(self):
        self.assertFalse(looks_like_heading("257.3"))
        self.assertIn("257.3",chunk_pages([Page(4,"257.3")])[0].text)
    def test_pages_and_sections_not_merged(self):
        chunks=merge_short_chunks(chunk_pages([Page(2,"FUEL\n380 bar."),Page(9,"COOLANT\nNever open hot.")]))
        self.assertEqual([2,9],[c.page_start for c in chunks])
        self.assertTrue(all(c.page_start==c.page_end for c in chunks))
    def test_split_does_not_invent_punctuation(self):
        text="Pressure is 3.8 bar. Never open hot! Code AZ-17 remains"
        pieces=split_long_paragraph(text,20)
        self.assertEqual(" ".join(pieces),text)
    def test_inline_heading_is_found_without_losing_body(self):
        chunks=chunk_pages([Page(5,"A normal paragraph.\nOhm’s Law (Resistance)\nVoltage, current and resistance are related.")])
        self.assertTrue(any(c.section=="Ohm’s Law (Resistance)" and "resistance are related" in c.text for c in chunks))
        self.assertFalse(looks_like_heading("ESH = EM"))
        self.assertFalse(looks_like_heading("Where:"))
    def test_publisher_parent_context_keeps_leaf_citation(self):
        page=Page(4,"Intake Stroke\nThe piston moves down.",section_paths={"Intake Stroke":"Engines > Four-Stroke Cycle > Intake Stroke"})
        chunk=chunk_pages([page])[0]
        self.assertEqual("Intake Stroke",chunk.section)
        self.assertIn("Four-Stroke Cycle",chunk.search_context)
        self.assertNotIn("Engines >",chunk.text)
    def test_table_rows_remain_complete(self):
        rows=["AZ-%02d pressure 3.8 bar"%i for i in range(20)]
        pieces=split_long_paragraph("\n".join(rows),80)
        for row in rows:self.assertTrue(any(row in p for p in pieces))
if __name__=='__main__': unittest.main()
