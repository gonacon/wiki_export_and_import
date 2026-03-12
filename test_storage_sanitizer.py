#!/usr/bin/env python3
import unittest

from src.wiki_migration.sanitizer import Sanitizer


class RepairBrokenConfluenceLinksTest(unittest.TestCase):
    def test_removes_orphan_closing_link_tags_from_actual_pattern(self):
        html = '''<p>
    <ac:image ac:alt="스크린샷 2024-01-23 오후 9.06.07.png">
        <ri:attachment ri:filename="스크린샷 2024-01-23 오후 9.06.07.png"/>
    </ac:image>
    </ac:link-body></ac:link></p>'''

        repaired = Sanitizer.repair_broken_confluence_links(html)

        self.assertIn('</ac:image>', repaired)
        self.assertNotIn('</ac:link-body>', repaired)
        self.assertNotIn('</ac:link></p>', repaired)
        self.assertEqual(repaired.count('<ac:image'), 1)
        self.assertEqual(repaired.count('</ac:image>'), 1)

    def test_keeps_valid_link_markup_intact(self):
        html = '<p><ac:link><ri:attachment ri:filename="a.png" /><ac:link-body>다운로드</ac:link-body></ac:link></p>'

        repaired = Sanitizer.repair_broken_confluence_links(html)

        self.assertEqual(repaired, html)

    def test_auto_closes_left_open_link_tags(self):
        html = '<p><ac:link><ri:attachment ri:filename="a.png" /><ac:link-body>다운로드</p>'

        repaired = Sanitizer.repair_broken_confluence_links(html)

        self.assertTrue(repaired.endswith('</ac:link-body></ac:link>'))
        self.assertIn('<ac:link>', repaired)
        self.assertIn('<ac:link-body>', repaired)


if __name__ == '__main__':
    unittest.main(verbosity=2)
