import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.wiki_migration import importer


class DestinationSpaceTest(unittest.TestCase):
    def test_title_lookup_failure_does_not_create_page(self):
        def get_response(url, params=None, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            if url.endswith('/content/parent'):
                response.json.return_value = {'space': {'key': 'GICON'}}
                return response
            raise TimeoutError('lookup timed out')

        with patch.object(importer, 'NEW_SPACE', 'PERSONAL'), \
             patch.object(importer.new_session, 'get', side_effect=get_response), \
             patch.object(importer.new_session, 'post') as post:
            with self.assertRaisesRegex(RuntimeError, '페이지 조회 실패'):
                importer.create_page('Existing title', '<p>placeholder</p>', parent='parent')

        post.assert_not_called()

    def test_existing_page_lookup_uses_parent_space(self):
        def get_response(url, params=None, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            if url.endswith('/content/parent'):
                response.json.return_value = {'space': {'key': 'GICON'}}
            elif url.endswith('/rest/api/content'):
                response.json.return_value = {
                    'results': [{'id': 'existing-page'}]
                    if params.get('spaceKey') == 'GICON' else []
                }
            else:
                response.json.return_value = {'version': {'number': 1}}
            return response

        with patch.object(importer, 'NEW_SPACE', 'PERSONAL'), \
             patch.object(importer.new_session, 'get', side_effect=get_response), \
             patch.object(importer.new_session, 'put') as put, \
             patch.object(importer.new_session, 'post') as post:
            put.return_value.json.return_value = {'id': 'existing-page'}
            post.return_value.status_code = 201
            post.return_value.json.return_value = {'id': 'new-page'}

            page_id = importer.create_page(
                'Existing title', '<p>placeholder</p>', parent='parent'
            )

        self.assertEqual(page_id, 'existing-page')
        self.assertEqual(put.call_args.kwargs['json']['space']['key'], 'GICON')
        post.assert_not_called()

    def test_existing_page_cannot_be_moved_under_its_descendant(self):
        def get_response(url, params=None, timeout=None):
            response = Mock()
            response.raise_for_status.return_value = None
            if url.endswith('/content/parent'):
                response.json.return_value = {
                    'space': {'key': 'GICON'},
                    'ancestors': [{'id': 'existing-page'}],
                }
            else:
                response.json.return_value = {
                    'results': [{'id': 'existing-page'}],
                }
            return response

        with patch.object(importer.new_session, 'get', side_effect=get_response), \
             patch.object(importer, 'update_page') as update_page:
            with self.assertRaisesRegex(RuntimeError, '하위'):
                importer.create_page('Existing title', '<p>placeholder</p>', parent='parent')

        update_page.assert_not_called()

    def test_two_pass_selected_root_uses_requested_parent(self):
        with tempfile.TemporaryDirectory() as export_dir:
            os.makedirs(os.path.join(export_dir, 'pages'))
            root_folder = os.path.join(export_dir, 'root')
            child_folder = os.path.join(export_dir, 'child')
            os.makedirs(root_folder)
            os.makedirs(child_folder)
            for folder in (root_folder, child_folder):
                with open(os.path.join(folder, 'page.storage.html'), 'w', encoding='utf-8') as html:
                    html.write('<p>content</p>')

            pages_info = {
                'root': {
                    'meta': {'id': 'root', 'title': 'Root', 'parent': 'source-parent'},
                    'folder': root_folder,
                    'children': ['child'],
                },
                'child': {
                    'meta': {'id': 'child', 'title': 'Child', 'parent': 'root'},
                    'folder': child_folder,
                    'children': [],
                },
            }
            resume_state = {'page_map': {'source-parent': 'stale-parent'}, 'uploaded': []}
            created_parents = []
            updated_parents = []

            def create_page(title, body_html, parent=None):
                created_parents.append((title, parent))
                return 'destination-root' if title == 'Root' else 'destination-child'

            def update_page(page_id, title, body_html, parent=None):
                updated_parents.append((title, parent))
                return page_id

            with patch.object(importer, 'EXPORT_DIR', export_dir), \
                 patch.object(importer, 'MAX_WORKERS', 1), \
                 patch.object(importer, 'build_page_hierarchy', return_value=pages_info), \
                 patch.object(importer, 'load_resume_state', return_value=resume_state), \
                 patch.object(importer, 'save_resume_state'), \
                 patch.object(importer, 'create_page', side_effect=create_page), \
                 patch.object(importer, 'update_page', side_effect=update_page), \
                 patch.object(importer, 'upload_attachments'):
                importer.import_all_two_pass(
                    force_update=True,
                    root_page_id='root',
                    target_parent_id='requested-parent',
                )

        self.assertEqual(created_parents[0], ('Root', 'requested-parent'))
        self.assertIn(('Root', 'requested-parent'), updated_parents)
        self.assertIn(('Child', 'destination-root'), created_parents)
        self.assertIn(('Child', 'destination-root'), updated_parents)


if __name__ == '__main__':
    unittest.main(verbosity=2)