import ssl
import unittest
from unittest.mock import MagicMock,patch
from src.mailer import send_account_link,send_verification,MailUnavailable


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict('os.environ',{'SMTP_HOST':'smtp.gmail.com','SMTP_PORT':'465','SMTP_USERNAME':'sender@example.test','SMTP_PASSWORD':'test app password','SMTP_FROM':'sender@example.test','ACCOUNTS_PUBLIC_ORIGIN':'https://app.example.test','ACCOUNTS_DEV_HTTP':'0'},clear=True)
        self.env.start()
    def tearDown(self):self.env.stop()

    def test_implicit_tls_sender_and_fragment_link(self):
        with patch('src.mailer.smtplib.SMTP_SSL') as smtp:
            send_verification('recipient@example.test','verify_synthetic-token')
        smtp.assert_called_once()
        self.assertEqual(smtp.call_args.args,('smtp.gmail.com',465))
        self.assertIsInstance(smtp.call_args.kwargs['context'],ssl.SSLContext)
        client=smtp.return_value.__enter__.return_value
        client.login.assert_called_once_with('sender@example.test','testapppassword')
        message=client.send_message.call_args.args[0]
        self.assertIn('sender@example.test',str(message['From']))
        self.assertEqual(str(message['To']),'recipient@example.test')
        self.assertIn('https://app.example.test/#verify=verify_synthetic-token',message.get_content())

    def test_starttls_before_authentication(self):
        with patch.dict('os.environ',{'SMTP_PORT':'587'}),patch('src.mailer.smtplib.SMTP') as smtp:
            send_verification('recipient@example.test','verify_synthetic-token')
        calls=[c[0] for c in smtp.return_value.__enter__.return_value.mock_calls]
        self.assertLess(calls.index('starttls'),calls.index('login'))

    def test_account_links_use_distinct_fragments_and_expiry(self):
        for purpose, fragment in [('reset','reset-password'), ('delete','delete-confirm')]:
            with self.subTest(purpose=purpose), patch('src.mailer.smtplib.SMTP_SSL') as smtp:
                send_account_link('recipient@example.test', purpose + '_synthetic', purpose)
                message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
                self.assertIn('https://app.example.test/#' + fragment + '=' + purpose + '_synthetic', message.get_content())
                self.assertIn('30 menit', message.get_content())

    def test_provider_errors_do_not_disclose_credentials(self):
        with patch('src.mailer.smtplib.SMTP_SSL',side_effect=Exception('secret-password-or-provider-details')):
            with self.assertRaises(MailUnavailable) as result:send_verification('recipient@example.test','verify_synthetic-token')
        self.assertNotIn('secret-password',str(result.exception))

    def test_rejects_cleartext_port_or_untrusted_public_origin(self):
        for config in [{'SMTP_PORT':'25'},{'ACCOUNTS_PUBLIC_ORIGIN':'http://public.example.test'},{'ACCOUNTS_PUBLIC_ORIGIN':'https://evil@example.test'},{'SMTP_PASSWORD':''}]:
            with self.subTest(config=config),patch.dict('os.environ',config),patch('src.mailer.smtplib.SMTP_SSL') as smtp:
                with self.assertRaises(MailUnavailable):send_verification('recipient@example.test','verify_synthetic-token')
                smtp.assert_not_called()

    def test_private_password_file_and_unsafe_permissions(self):
        import os,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            secret=Path(directory)/'smtp-secret'
            secret.write_text('synthetic-file-password\n')
            os.chmod(secret,0o600)
            with patch.dict('os.environ',{'SMTP_PASSWORD_FILE':str(secret)}),patch('src.mailer.smtplib.SMTP_SSL') as smtp:
                send_verification('recipient@example.test','verify_synthetic-token')
                smtp.return_value.__enter__.return_value.login.assert_called_once_with('sender@example.test','synthetic-file-password')
            os.chmod(secret,0o644)
            with patch.dict('os.environ',{'SMTP_PASSWORD_FILE':str(secret)}),patch('src.mailer.smtplib.SMTP_SSL') as smtp:
                with self.assertRaises(MailUnavailable):send_verification('recipient@example.test','verify_synthetic-token')
                smtp.assert_not_called()
