import unittest
from unittest.mock import patch

from app.bot import select_jobs


class RolePriorityTests(unittest.TestCase):
    def test_preferred_roles_rank_first(self):
        roles = ["senior qa automation engineer", "sdet", "automation test engineer"]
        with patch.object(select_jobs, "PREFERRED_ROLES", roles):
            self.assertEqual(select_jobs._role_priority("Senior QA Automation Engineer"), 0)
            self.assertEqual(select_jobs._role_priority("SDET"), 1)
            self.assertEqual(select_jobs._role_priority("Automation Test Engineer @ X"), 2)
            self.assertEqual(select_jobs._role_priority("Salesforce Developer"), len(roles))

    def test_empty_roles_returns_neutral_rank(self):
        with patch.object(select_jobs, "PREFERRED_ROLES", []):
            self.assertEqual(select_jobs._role_priority("Anything"), 0)

    def test_job_key_uses_url_when_present(self):
        self.assertEqual(
            select_jobs._job_key({"url": "https://x", "title": "T", "company": "C"}),
            "https://x",
        )
        self.assertEqual(
            select_jobs._job_key({"title": "T", "company": "C"}),
            "T|C",
        )


if __name__ == "__main__":
    unittest.main()
