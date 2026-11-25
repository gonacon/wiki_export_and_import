import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.wiki_migration import importer


class UploadAttachmentsTest(unittest.TestCase):
    def test_existing_remote_attachment_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            attachments = os.path.join(folder, 'attachments')
            os.makedirs(attachments)
            with open(os.path.join(attachments, 'stored.png'), 'wb') as file:
                file.write(b'already uploaded')
            with open(os.path.join(attachments, 'new.png'), 'wb') as file:
                file.write(b'new attachment')
            with open(os.path.join(attachments, 'manifest.json'), 'w', encoding='utf-8') as file:
                json.dump({'title_map': {'existing.png': 'stored.png'}}, file)

            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {'results': [{'title': 'existing.png'}]}
            upload_response = Mock(status_code=200)
            with patch.object(importer.new_session, 'get', return_value=response) as get, \
                 patch.object(importer.new_session, 'post', return_value=upload_response) as post:
                importer.upload_attachments('destination-page', folder)

        get.assert_called_once()
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['files']['file'][0], 'new.png')

    def test_existing_korean_attachment_is_skipped_across_unicode_forms(self):
        with tempfile.TemporaryDirectory() as folder:
            attachments = os.path.join(folder, 'attachments')
            os.makedirs(attachments)
            stored_name = '한글.png'
            remote_name = '한글.png'
            with open(os.path.join(attachments, stored_name), 'wb') as file:
                file.write(b'attachment')
            with open(os.path.join(attachments, 'manifest.json'), 'w', encoding='utf-8') as file:
                json.dump({'title_map': {stored_name: stored_name}}, file, ensure_ascii=False)

            response = Mock()
            response.raise_for_status.return_value = None
            response.json.return_value = {'results': [{'title': remote_name}]}
            with patch.object(importer.new_session, 'get', return_value=response), \
                 patch.object(importer.new_session, 'post') as post:
                importer.upload_attachments('destination-page', folder)

        post.assert_not_called()

    def test_attachment_listing_failure_stops_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            attachments = os.path.join(folder, 'attachments')
            os.makedirs(attachments)
            with open(os.path.join(attachments, 'attachment.png'), 'wb') as file:
                file.write(b'attachment')

            response = Mock()
            response.raise_for_status.side_effect = RuntimeError('service unavailable')
            with patch.object(importer.new_session, 'get', return_value=response), \
                 patch.object(importer.new_session, 'post') as post:
                with self.assertRaisesRegex(RuntimeError, '업로드를 중단합니다'):
                    importer.upload_attachments('destination-page', folder)

        post.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)