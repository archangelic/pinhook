"""SASL logins: PLAIN, SCRAM-SHA-256 and EXTERNAL.

SCRAM-SHA-256 (RFC 5802 and 7677) proves the bot knows the password without
sending it, and checks the server knows it too. EXTERNAL logs in with the
client certificate the connection was made with.
"""
import base64
import hashlib
import hmac
import secrets

# best first, when the server lists what it offers
PREFERRED = ('EXTERNAL', 'SCRAM-SHA-256', 'PLAIN')


class SaslError(Exception):
    """The server's side of a login didn't add up, like a SCRAM signature that's wrong."""


def choose(offered, has_password, has_cert, wanted='auto'):
    """The mechanism to log in with, or None if there's nothing usable.

    Args:
        offered: the mechanisms the server lists, upper case, or None if it didn't say.
        has_password: True if there's a sasl_password.
        has_cert: True if the connection has a client certificate.
        wanted: 'auto', or one mechanism the owner insists on.
    """
    usable = [m for m in PREFERRED
              if (m == 'EXTERNAL' and has_cert) or (m != 'EXTERNAL' and has_password)]
    if wanted != 'auto':
        usable = [m for m in usable if m == wanted.upper()]
    if offered is None:
        # a server that doesn't list its mechanisms gets the one every server has, unless
        # the owner chose
        return usable[0] if wanted != 'auto' and usable else ('PLAIN' if has_password else None)
    return next((m for m in usable if m in offered), None)


class Plain:
    name = 'PLAIN'

    def __init__(self, account, password):
        self.account, self.password = account, password

    def respond(self, challenge):
        return '\0{}\0{}'.format(self.account, self.password).encode('utf-8')


class External:
    name = 'EXTERNAL'

    def respond(self, challenge):
        # an empty answer: log in as whoever the certificate belongs to
        return b''


class ScramSha256:
    """One SCRAM-SHA-256 login, answering the server's challenges in turn."""
    name = 'SCRAM-SHA-256'

    def __init__(self, account, password, nonce=None):
        self.account = account
        self.password = password.encode('utf-8')
        self.nonce = nonce or base64.b64encode(secrets.token_bytes(18)).decode('ascii')
        self.step = 0
        self.server_signature = None

    def respond(self, challenge):
        self.step += 1
        if self.step == 1:
            # a = and , in the name are written =3D and =2C
            name = self.account.replace('=', '=3D').replace(',', '=2C')
            self.first_bare = 'n={},r={}'.format(name, self.nonce)
            return ('n,,' + self.first_bare).encode('utf-8')
        if self.step == 2:
            return self.final(challenge.decode('utf-8'))
        if self.step == 3:
            fields = parse(challenge.decode('utf-8'))
            if 'e' in fields:
                raise SaslError('the server refused the login: ' + fields['e'])
            if not hmac.compare_digest(base64.b64decode(fields.get('v', '')),
                                       self.server_signature):
                raise SaslError("the server's SCRAM signature is wrong, so it may not be "
                                "the real server")
            return b''
        raise SaslError('the server kept asking after the login was done')

    def final(self, server_first):
        fields = parse(server_first)
        nonce, salt, rounds = fields.get('r', ''), fields.get('s'), fields.get('i', '')
        if not nonce.startswith(self.nonce) or salt is None or not rounds.isdigit():
            raise SaslError("the server's SCRAM challenge doesn't make sense: " + server_first)
        salted = hashlib.pbkdf2_hmac('sha256', self.password, base64.b64decode(salt),
                                     int(rounds))
        client_key = mac(salted, b'Client Key')
        without_proof = 'c=biws,r=' + nonce
        auth_message = ','.join((self.first_bare, server_first, without_proof)).encode('utf-8')
        signature = mac(hashlib.sha256(client_key).digest(), auth_message)
        proof = bytes(a ^ b for a, b in zip(client_key, signature))
        self.server_signature = mac(mac(salted, b'Server Key'), auth_message)
        return '{},p={}'.format(without_proof,
                                base64.b64encode(proof).decode('ascii')).encode('utf-8')


def mac(key, message):
    return hmac.new(key, message, hashlib.sha256).digest()


def parse(message):
    # 'r=abc,s=salt,i=4096' -> {'r': 'abc', 's': 'salt', 'i': '4096'}
    fields = {}
    for part in message.split(','):
        name, _, value = part.partition('=')
        fields[name] = value
    return fields


def encode(response):
    """A response as the AUTHENTICATE lines that carry it: base64 in 400 byte pieces,
    with + for an empty one or after a last piece that's exactly 400."""
    encoded = base64.b64encode(response).decode('ascii')
    pieces = [encoded[i:i + 400] for i in range(0, len(encoded), 400)]
    if not pieces or len(pieces[-1]) == 400:
        pieces.append('+')
    return pieces
