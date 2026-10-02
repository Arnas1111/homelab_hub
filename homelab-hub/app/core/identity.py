"""First-run administrator setup and a session signing key persisted in appdata."""
import hashlib
import json
import secrets
import threading


class Identity:
    def __init__(self, directory):
        self.path = directory / 'administrator.json'
        self.access_path = directory / 'access.json'
        self.lock = threading.Lock()
        key_file = directory / 'session.key'
        if not key_file.exists():
            try:
                with key_file.open('x', encoding='utf-8') as stream:
                    stream.write(secrets.token_urlsafe(48))
                key_file.chmod(0o600)
            except FileExistsError:
                pass
        self.secret = key_file.read_text(encoding='utf-8').strip()

    def record(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else None

    def configured(self, environment_password):
        return self.path.exists() or bool(environment_password)

    def version(self):
        record = self.record()
        password_version = record['version'] if record else None
        access = self.access_record()
        return f"{password_version}:{access['version']}" if access else password_version

    def access_record(self):
        return json.loads(self.access_path.read_text(encoding='utf-8')) if self.access_path.exists() else None

    def login_required(self):
        access = self.access_record()
        return access['login_required'] if access else True

    def set_login_required(self, enabled):
        temporary = self.access_path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            temporary.chmod(0o600)
            json.dump({'login_required': enabled, 'version': secrets.token_hex(16)}, stream)
        temporary.replace(self.access_path)

    def verify(self, password, environment_password):
        record = self.record()
        if record:
            digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(record['salt']), 600000).hex()
            return secrets.compare_digest(digest, record['digest'])
        return bool(environment_password) and secrets.compare_digest(password.encode(), environment_password.encode())

    def save(self, password):
        salt = secrets.token_bytes(16)
        record = {'salt': salt.hex(), 'digest': hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000).hex(),
                  'version': secrets.token_hex(16)}
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            temporary.chmod(0o600)
            json.dump(record, stream)
        temporary.replace(self.path)
