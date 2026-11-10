import os
import tempfile
import unittest
from unittest.mock import patch

import openpyxl

from app.utils import answer_sheet


def _fake_history():
    return [{
        "question": "What is your notice period?",
        "options": "",
        "answer_given": "60 days",
        "count": 3,
        "last_asked": "2026-11-10 10:00:00",
        "sources": ["report.json"],
    }]


class AnswerSheetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "Question_Answers.xlsx")
        self.addCleanup(self.tmp.cleanup)

    def _write_override(self, question: str, answer: str):
        answer_sheet.refresh_answer_sheet(self.path)
        wb = openpyxl.load_workbook(self.path)
        ws = wb["Q&A Log"]
        headers = {c.value: c.column for c in ws[1]}
        ws.cell(row=2, column=headers["Question"], value=question)
        ws.cell(row=2, column=headers["Your Answer"], value=answer)
        wb.save(self.path)

    def test_override_is_returned_for_exact_question(self):
        self._write_override("What is your notice period?", "15 Days or less")
        with patch.object(answer_sheet, "SHEET_PATH", self.path):
            self.assertEqual(
                answer_sheet.find_curated_answer("What is your notice period?"),
                "15 Days or less",
            )
            self.assertIsNone(answer_sheet.find_curated_answer("Some other question?"))

    def test_refresh_preserves_user_edits(self):
        with patch.object(answer_sheet, "collect_history", return_value=_fake_history()):
            answer_sheet.refresh_answer_sheet(self.path)

        self._write_override("What is your notice period?", "Immediate")

        with patch.object(answer_sheet, "collect_history", return_value=_fake_history()):
            answer_sheet.refresh_answer_sheet(self.path)

        curated = answer_sheet.load_curated_answers(self.path)
        self.assertEqual(curated.get("what is your notice period?"), "Immediate")

    def test_blank_answer_is_not_curated(self):
        self._write_override("What is your notice period?", "")
        curated = answer_sheet.load_curated_answers(self.path)
        self.assertNotIn("what is your notice period?", curated)


if __name__ == "__main__":
    unittest.main()
