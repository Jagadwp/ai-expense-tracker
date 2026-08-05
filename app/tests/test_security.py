import base64
import os

import pytest

from app.security import Encryptor


def _random_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


@pytest.mark.parametrize(
    "bad_key",
    [
        "this is not base64!!!",
        base64.b64encode(b"short").decode(),
        "",
    ],
)
def test_new_encryptor_invalid_key(bad_key):
    with pytest.raises(ValueError):
        Encryptor(bad_key)


def test_encrypt_decrypt_round_trip():
    enc = Encryptor(_random_key())
    plaintext = b"ya29.a0AfH6SMexample-oauth-token"

    ciphertext = enc.encrypt(plaintext)
    assert ciphertext != plaintext

    assert enc.decrypt(ciphertext) == plaintext


def test_encrypt_unique_nonce_per_call():
    enc = Encryptor(_random_key())
    plaintext = b"same input"

    a = enc.encrypt(plaintext)
    b = enc.encrypt(plaintext)

    assert a != b


def test_decrypt_wrong_key_fails():
    enc_a = Encryptor(_random_key())
    enc_b = Encryptor(_random_key())

    ciphertext = enc_a.encrypt(b"secret")

    with pytest.raises(Exception):
        enc_b.decrypt(ciphertext)


def test_decrypt_tampered_ciphertext_fails():
    enc = Encryptor(_random_key())
    ciphertext = bytearray(enc.encrypt(b"secret"))

    ciphertext[-1] ^= 0x01  # flip a bit in the last byte

    with pytest.raises(Exception):
        enc.decrypt(bytes(ciphertext))


def test_decrypt_too_short_fails():
    enc = Encryptor(_random_key())

    with pytest.raises(ValueError):
        enc.decrypt(b"short")
