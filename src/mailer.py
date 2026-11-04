"""Transactional verification mail. No plaintext SMTP or credential logging."""
from email.message import EmailMessage
from email.utils import formataddr
import os
from pathlib import Path
import smtplib
import ssl
from urllib.parse import urlsplit


class MailUnavailable(Exception):
    pass


def send_verification(recipient: str, token: str) -> None:
    _send(recipient, token, 'verify', 'Verifikasi email akun MCP Satu Data Aceh',
          'Konfirmasikan email untuk mengaktifkan akun Anda.', 'Verifikasi email', '1 jam')


def send_account_link(recipient: str, token: str, purpose: str) -> None:
    if purpose == 'reset':
        _send(recipient, token, 'reset-password', 'Atur ulang sandi MCP Satu Data Aceh',
              'Ada permintaan untuk mengatur ulang sandi akun Anda.', 'Simpan sandi baru', '30 menit')
    else:
        _send(recipient, token, 'delete-confirm', 'Konfirmasi penghapusan akun MCP Satu Data Aceh',
              'Ada permintaan untuk menghapus akun Anda beserta akses dan API key yang tersimpan.',
              'Hapus akun secara permanen', '30 menit')


def _send(recipient, token, route, subject, intro, action, duration):
    username = os.getenv('SMTP_USERNAME', '')
    try:
        secret_file = os.getenv('SMTP_PASSWORD_FILE', '')
        if secret_file:
            secret_path = Path(secret_file)
            if os.name == 'posix' and secret_path.stat().st_mode & 0o077:
                raise MailUnavailable('Berkas password SMTP harus dibatasi ke pemiliknya.')
            password = secret_path.read_text(encoding='utf-8').strip()
        else:
            password = os.getenv('SMTP_PASSWORD', '')
        password = password.replace(' ', '')
    except (OSError, UnicodeError):
        raise MailUnavailable('Berkas rahasia SMTP belum dapat dibaca.') from None
    sender = os.getenv('SMTP_FROM', username)
    origin = os.getenv('ACCOUNTS_PUBLIC_ORIGIN', 'https://www.mcpsatudataaceh.web.id').rstrip('/')
    parsed = urlsplit(origin)
    dev_loopback = os.getenv('ACCOUNTS_DEV_HTTP') == '1' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}
    if not username or not password or not sender or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.netloc or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and dev_loopback)):
        raise MailUnavailable('Konfigurasi email belum siap.')
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = formataddr(('MCP Satu Data Aceh', sender))
    message['To'] = recipient
    # Fragments are not sent in HTTP requests or included in server access logs.
    link = origin + '/#' + route + '=' + token
    message.set_content(
        f'Halo,\n\n{intro}\n'
        f'Buka tautan berikut, lalu tekan tombol {action}:\n\n{link}\n\n'
        f'Tautan berlaku {duration} dan hanya dapat digunakan sekali.\n'
        'Jika Anda tidak meminta tindakan ini, abaikan pesan ini. Jangan membagikan tautan kepada orang lain.\n\n'
        'MCP Satu Data Aceh — proyek independen, bukan layanan resmi BPS.\n'
    )
    context = ssl.create_default_context()
    try:
        port = int(os.getenv('SMTP_PORT', '465'))
        host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
                smtp.login(username, password)
                smtp.send_message(message)
        elif port == 587:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(username, password)
                smtp.send_message(message)
        else:
            raise MailUnavailable('Port SMTP harus 465 atau 587 dengan TLS.')
    except Exception:
        # SMTP provider errors can echo addresses and credentials. Never expose them.
        raise MailUnavailable('Email belum dapat dikirim. Silakan coba lagi.') from None
