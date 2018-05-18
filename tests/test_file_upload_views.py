from flask import url_for
import io
from .base import AppTestCase


class AccountFileUpload(AppTestCase):
    # def test_user_not_authenticated___returns_401(self):
    #     url = url_for('root.account_file_upload')
    #     response = self.client.post(url)
    #     self.assertEqual(response.status_code, 401)

    def test_user_authenticated___file_appears_in_user_list_of_files(self):
        url = url_for('root.account_file_upload')
        a_file = io.BytesIO(b'a file')
        response = self.client.post(
            url,
            data=dict(
                file=(a_file, 'filename-is-ignored.file')
            )
        )
        # filename = response.json['filename']
        # self.assertIn(filename, user_file_list)
