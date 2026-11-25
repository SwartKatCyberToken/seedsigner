"""Unit tests for deterministic message keys and v1 envelopes.

These tests do not start the SeedSigner UI. RSA generation uses 1024-bit
keys so the suite stays short; the device default remains 2048. The HKDF
vector is the v1 recovery contract for the abandon BIP-39 seed.
"""

import hashlib

import pytest
from embit import bip39

from seedsigner.message_crypto.codec import dumps, parse_document
from seedsigner.message_crypto.derivation import (
    LABEL_ML_DSA,
    LABEL_ML_KEM,
    LABEL_RSA_ENCRYPT,
    LABEL_RSA_SIGN,
    ML_DSA_SEED_LENGTH,
    ML_KEM_SEED_LENGTH,
    RSA_STREAM_LENGTH,
    HmacSha256Counter,
    derive_material,
)
from seedsigner.message_crypto.errors import MessageCryptoError
from seedsigner.message_crypto.keys import MessageKeys, clear_cache, keys_for_seed
from seedsigner.message_crypto.operations import (
    decrypt_with,
    encrypt_for,
    export_public,
    sign_with,
    verify_with,
)
from seedsigner.message_crypto.qr_codec import QrAssembly, split_frames
from seedsigner.message_crypto import pgp_ops
from seedsigner.message_crypto.sanitize import WANT_ENVELOPE, WANT_PUB, WANT_SIGNATURE, parse_input
from seedsigner.message_crypto.codec import (
    ALG_ML_DSA,
    ALG_ML_KEM,
    ALG_PGP_ENCRYPT,
    ALG_PGP_SIGN,
    ALG_RSA_ENCRYPT,
    ALG_RSA_SIGN,
    split_signed_block,
)

ABANDON_MNEMONIC = " ".join(["abandon"] * 11 + ["about"])
ABANDON_SEED = bytes.fromhex(
    "5eb00bbddcf069084889a8ab9155568165f5c453ccb85e70811aaed6f6da5fc1"
    "9a5ac40b389cd370d086206dec8aa6c43daea6690f20ad3d8d48b2d2ce9e38e4"
)
# HKDF-SHA256 of ABANDON_SEED for label ml-dsa-44. Locked so a scheme edit fails.
ABANDON_ML_DSA_SEED = bytes.fromhex(
    "36806ed8d19a3d562aa583aee2087cf16676e5dc757baa82391427c55508abc4"
)


def abandon_seed() -> bytes:
    seed = bip39.mnemonic_to_seed(ABANDON_MNEMONIC, password="")
    assert seed == ABANDON_SEED
    return seed


def test_domain_labels_are_distinct_and_stable():
    seed = abandon_seed()
    labels = (LABEL_RSA_SIGN, LABEL_RSA_ENCRYPT, LABEL_ML_DSA, LABEL_ML_KEM)
    lengths = (RSA_STREAM_LENGTH, RSA_STREAM_LENGTH, ML_DSA_SEED_LENGTH, ML_KEM_SEED_LENGTH)
    outputs = [derive_material(seed, label, length) for label, length in zip(labels, lengths)]
    assert len(set(outputs)) == 4
    again = [derive_material(seed, label, length) for label, length in zip(labels, lengths)]
    assert outputs == again
    other = hashlib.sha256(seed).digest() + hashlib.sha256(seed).digest()
    assert derive_material(other, LABEL_ML_DSA, ML_DSA_SEED_LENGTH) != outputs[2]


def test_rand_stream_is_not_the_seed_and_is_repeatable():
    seed = abandon_seed()
    key = derive_material(seed, LABEL_RSA_SIGN, RSA_STREAM_LENGTH)
    first = HmacSha256Counter(key)
    second = HmacSha256Counter(key)
    chunk = first(64)
    assert chunk == second(64)
    assert seed not in chunk
    assert key not in chunk
    assert chunk[:32] != chunk[32:]


def test_ml_dsa_derivation_vector():
    material = derive_material(abandon_seed(), LABEL_ML_DSA, ML_DSA_SEED_LENGTH)
    assert material == ABANDON_ML_DSA_SEED


def test_bad_seed_length_is_rejected():
    with pytest.raises(MessageCryptoError, match="64 bytes"):
        derive_material(b"\x00" * 32, LABEL_ML_DSA, ML_DSA_SEED_LENGTH)


def test_rsa_keypair_is_stable_and_signs():
    clear_cache()
    seed = abandon_seed()
    first = MessageKeys(seed, rsa_bits=1024).rsa_signing_key()
    second = MessageKeys(seed, rsa_bits=1024).rsa_signing_key()
    assert first.export_key() == second.export_key()
    signing = MessageKeys(seed, rsa_bits=1024)
    encrypting = MessageKeys(seed, rsa_bits=1024)
    assert signing.rsa_signing_key().n != encrypting.rsa_encryption_key().n
    public = export_public(signing, ALG_RSA_SIGN)
    envelope = sign_with(signing, ALG_RSA_SIGN, "hello")
    assert verify_with(public, envelope) is True
    envelope["msg"] = "hello!"
    assert verify_with(public, parse_document(dumps(envelope))) is False


def test_rsa_hybrid_roundtrip_and_tamper():
    clear_cache()
    alice = MessageKeys(abandon_seed(), rsa_bits=1024)
    bob_seed = hashlib.sha256(b"bob").digest() + hashlib.sha256(b"bob").digest()
    bob = MessageKeys(bob_seed, rsa_bits=1024)
    peer = export_public(bob, ALG_RSA_ENCRYPT)
    envelope = encrypt_for(alice, ALG_RSA_ENCRYPT, peer, "secret message")
    assert decrypt_with(bob, envelope) == "secret message"
    other = encrypt_for(alice, ALG_RSA_ENCRYPT, peer, "secret message")
    assert other["ct"] != envelope["ct"]
    broken = dict(envelope)
    broken["ct"] = envelope["nonce"]
    broken = parse_document(dumps(broken))
    with pytest.raises(MessageCryptoError, match="authentication failed"):
        decrypt_with(bob, broken)
    with pytest.raises(MessageCryptoError, match="RSA encryption"):
        encrypt_for(alice, ALG_RSA_ENCRYPT, export_public(bob, ALG_RSA_SIGN), "secret message")


def test_ml_dsa_sign_verify_and_tamper():
    clear_cache()
    keys = MessageKeys(abandon_seed())
    again = MessageKeys(abandon_seed())
    assert keys.ml_dsa_keys()[0] == again.ml_dsa_keys()[0]
    public = export_public(keys, ALG_ML_DSA)
    envelope = sign_with(keys, ALG_ML_DSA, "post quantum")
    assert verify_with(public, envelope) is True
    same = sign_with(again, ALG_ML_DSA, "post quantum")
    assert envelope["sig"] == same["sig"]
    damaged = parse_document(dumps({**envelope, "msg": "post quantun"}))
    assert verify_with(public, damaged) is False
    with pytest.raises(MessageCryptoError, match="malformed ML-DSA signature length"):
        verify_with(public, {**envelope, "sig": "aa"})


def test_ml_kem_shared_secret_roundtrip():
    clear_cache()
    alice = MessageKeys(abandon_seed())
    bob = MessageKeys(hashlib.sha256(b"kem").digest() * 2)
    assert alice.ml_kem_keys()[0] == MessageKeys(abandon_seed()).ml_kem_keys()[0]
    peer = export_public(bob, ALG_ML_KEM)
    first = encrypt_for(alice, ALG_ML_KEM, peer, "capsule")
    second = encrypt_for(alice, ALG_ML_KEM, peer, "capsule")
    assert first["ek"] != second["ek"]
    assert decrypt_with(bob, first) == "capsule"
    assert decrypt_with(bob, second) == "capsule"
    tampered = parse_document(dumps({**first, "ct": second["ct"]}))
    with pytest.raises(MessageCryptoError, match="authentication failed"):
        decrypt_with(bob, tampered)


def test_envelope_rejects_malformed_input():
    with pytest.raises(MessageCryptoError, match="not JSON"):
        parse_document("not-json")
    with pytest.raises(MessageCryptoError, match="empty"):
        parse_document("")
    with pytest.raises(MessageCryptoError, match="unexpected field"):
        parse_document('{"v":1,"op":"text","msg":"hi","extra":1}')
    with pytest.raises(MessageCryptoError, match="empty"):
        from seedsigner.message_crypto.flow import accept_typed, new_flow
        flow = new_flow("sign")
        flow["expect"] = "text"
        accept_typed(flow, "")


def test_qr_frames_roundtrip_out_of_order():
    payload = dumps({"v": 1, "op": "text", "msg": "x" * 400})
    frames = split_frames(payload, fragment_chars=50)
    assert len(frames) > 1
    assembly = QrAssembly()
    statuses = [assembly.add(frame) for frame in reversed(frames)]
    assert statuses[-1] == "complete"
    assert assembly.payload == payload
    assert parse_document(assembly.payload)["msg"] == "x" * 400
    assert assembly.add(frames[0]) == "existing"


def test_keys_cache_forgets_a_seed():
    clear_cache()
    seed = abandon_seed()
    first = keys_for_seed(seed, rsa_bits=1024)
    assert keys_for_seed(seed, rsa_bits=1024) is first
    from seedsigner.message_crypto.keys import forget_seed_bytes
    forget_seed_bytes(seed)
    assert keys_for_seed(seed, rsa_bits=1024) is not first


def test_pgp_uses_the_seed_rsa_keys():
    clear_cache()
    keys = keys_for_seed(abandon_seed(), rsa_bits=1024)
    encrypt_pub = export_public(keys, ALG_PGP_ENCRYPT)
    sign_pub = export_public(keys, ALG_PGP_SIGN)
    assert export_public(keys, ALG_PGP_ENCRYPT) == encrypt_pub
    assert encrypt_pub["alg"] == ALG_PGP_ENCRYPT
    assert sign_pub["alg"] == ALG_PGP_SIGN
    assert encrypt_pub["armor"] == sign_pub["armor"]

    envelope = encrypt_for(keys, ALG_PGP_ENCRYPT, encrypt_pub, "hello")
    assert decrypt_with(keys, envelope) == "hello"
    broken = dict(envelope)
    broken["armor"] = "-----BEGIN PGP MESSAGE-----\nAA==\n-----END PGP MESSAGE-----\n"
    with pytest.raises(MessageCryptoError):
        decrypt_with(keys, broken)

    signed = sign_with(keys, ALG_PGP_SIGN, "hello")
    assert verify_with(sign_pub, signed) is True
    signed["msg"] = "hellp"
    assert verify_with(sign_pub, signed) is False


def test_decode_qr_reassembles_ssmsg1():
    pytest.importorskip("pyzbar")
    from seedsigner.models.decode_qr import DecodeQR, DecodeQRStatus

    payload = dumps({"v": 1, "op": "text", "msg": "scan me"})
    frames = split_frames(payload, fragment_chars=20)
    decoder = DecodeQR()
    status = None
    for frame in frames:
        status = decoder.add_data(frame)
    assert status == DecodeQRStatus.COMPLETE
    assert decoder.is_message_crypto
    assert decoder.get_qr_data()["msg"] == "scan me"


def test_message_qr_defaults_to_medium_density_and_speed():
    from seedsigner.models.message_qr import MessageAnimatedQrEncoder
    from seedsigner.models.settings_definition import SettingsConstants, SettingsDefinition

    encoder = MessageAnimatedQrEncoder(payload="x" * 200)
    assert encoder.qr_max_fragment_size == 90
    assert encoder.seq_len() == 3
    assert encoder.frame_delay_seconds == 10 / 30.0
    defaults = SettingsDefinition.get_defaults()
    assert defaults[SettingsConstants.SETTING__QR_DENSITY] == SettingsConstants.DENSITY__MEDIUM
    assert defaults[SettingsConstants.SETTING__MESSAGE_QR_SPEED] == SettingsConstants.QR_SPEED__MEDIUM


def test_message_qr_density_and_speed_options():
    from seedsigner.models.message_qr import MessageAnimatedQrEncoder
    from seedsigner.models.settings_definition import SettingsConstants

    payload = "x" * 200
    cases = [
        (SettingsConstants.DENSITY__LOW, 5, SettingsConstants.QR_SPEED__SLOW, 15 / 30.0),
        (SettingsConstants.DENSITY__HIGH, 2, SettingsConstants.QR_SPEED__FAST, 5 / 30.0),
    ]
    for density, frame_count, speed, delay in cases:
        encoder = MessageAnimatedQrEncoder(payload=payload, qr_density=density, qr_speed=speed)
        assert encoder.seq_len() == frame_count
        assert encoder.frame_delay_seconds == delay
        assembly = QrAssembly()
        for frame in encoder.parts:
            assembly.add(frame)
        assert assembly.payload == payload


SHAP_SIGN_KEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----

xjMEau0gVBYJKwYBBAHaRw8BAQdALX/eoi8B345hue6GGj2tRJkp6Ofhi9ip
ny0lpPPA8zLNG0pvbiBTbWl0aCA8am9uQGV4YW1wbGUuY29tPsKMBBAWCgA+
BYJq7SBUBAsJBwgJkJ9wibKGDi3EAxUICgQWAAIBAhkBApsDAh4BFiEEa8f4
XEQjrqCIVHCun3CJsoYOLcQAAOAvAPwO0nRpAQoiMQIXiDPycjtDHP2mvsOh
zjrUMiTccRLtHgD/VuBGfyid0rdpX7b0lmvx2uTUDQD64Ded13KwbY5V8wXO
OARq7SBUEgorBgEEAZdVAQUBAQdAAa668bqjYYWZxsS7CiMQYc88AJaYPaOu
u4Fa7ManY3IDAQgHwngEGBYKACoFgmrtIFQJkJ9wibKGDi3EApsMFiEEa8f4
XEQjrqCIVHCun3CJsoYOLcQAAF+4AP9U4HYFpRFKiJtZxjJl/mf30MLSgtry
9Jl/7rqWvPJphQD/RH31vH77p2GU6qldUm03YuiObSwp1n0M4zNLdH7hbgE=
=Tsrd
-----END PGP PUBLIC KEY BLOCK-----
"""
SHAP_SIGNED = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

pp
-----BEGIN PGP SIGNATURE-----

wnUEARYKACcFgmrtM9oJkJ9wibKGDi3EFiEEa8f4XEQjrqCIVHCun3CJsoYO
LcQAAHq1AQCzkG6PkI7qSG4XBPntLd9uhTwhfmfz5Q0NM+UT1mD8xQD/QHY2
VYF4BafKqDpN7ETIcoVc1YbM9YVRJCNI4WJQAAo=
=cz/W
-----END PGP SIGNATURE-----
"""


@pytest.fixture
def pgp_keys():
    clear_cache()
    return keys_for_seed(abandon_seed(), rsa_bits=1024)


@pytest.mark.parametrize("message", [
    "pp",
    "two\nlines",
    "- dash first\n-----BEGIN PGP SIGNATURE-----\nend",
    "ends in newline\n",
    "blank\n\n\nlines\n\n",
    "café € \U0001F600",
])
def test_pgp_signature_is_a_cleartext_block_that_survives_as_bare_text(pgp_keys, message):
    signed = sign_with(pgp_keys, ALG_PGP_SIGN, message)
    assert signed["armor"].startswith("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n")
    assert signed["msg"] == message
    public = export_public(pgp_keys, ALG_PGP_SIGN)
    assert verify_with(public, signed) is True
    bare = parse_input(signed["armor"], WANT_SIGNATURE)
    assert bare["msg"] == message
    assert verify_with(public, bare) is True


def test_pgp_signing_drops_line_end_spaces_as_cleartext_verifiers_do(pgp_keys):
    signed = sign_with(pgp_keys, ALG_PGP_SIGN, "a  \r\nb\t")
    assert signed["msg"] == "a\nb"
    assert verify_with(export_public(pgp_keys, ALG_PGP_SIGN), signed) is True


def test_pgp_message_of_only_spaces_is_rejected(pgp_keys):
    with pytest.raises(MessageCryptoError, match="empty"):
        sign_with(pgp_keys, ALG_PGP_SIGN, "   ")


def test_pgp_signature_is_never_older_than_the_key(pgp_keys, monkeypatch):
    class BootClock(pgp_ops.datetime):
        @classmethod
        def now(cls, tz=None):
            return pgp_ops.datetime(1970, 1, 1, 0, 3, 20, tzinfo=tz)

    armor_time = pgp_ops.KEY_CREATED
    monkeypatch.setattr(pgp_ops, "datetime", BootClock)
    assert pgp_ops._signature_time() == armor_time
    armor = sign_with(pgp_keys, ALG_PGP_SIGN, "hello")["armor"]
    monkeypatch.undo()
    pgpy, *_rest = pgp_ops._import_pgpy()
    signature = pgpy.PGPSignature.from_blob(split_signed_block(armor)[2])
    assert signature.created == armor_time


def test_changed_pgp_block_text_fails(pgp_keys):
    public = export_public(pgp_keys, ALG_PGP_SIGN)
    armor = sign_with(pgp_keys, ALG_PGP_SIGN, "hello")["armor"]
    assert verify_with(public, parse_input(armor.replace("\nhello\n", "\nhellp\n"), WANT_SIGNATURE)) is False


def test_pgp_block_from_another_key_fails(pgp_keys):
    peer = parse_input(SHAP_SIGN_KEY, WANT_PUB, ALG_PGP_SIGN)
    assert verify_with(peer, sign_with(pgp_keys, ALG_PGP_SIGN, "hello")) is False


def test_pgp_envelope_with_a_detached_signature_still_verifies(pgp_keys):
    public = export_public(pgp_keys, ALG_PGP_SIGN)
    _pgpy, _mpi, _pkt, _pkalg, _flags, HashAlgorithm, *_rest = pgp_ops._import_pgpy()
    private = pgp_ops.key_from_rsa(pgp_keys.rsa_signing_key(), "sign")
    signed = sign_with(pgp_keys, ALG_PGP_SIGN, "hello")
    signed["armor"] = str(private.sign("hello", hash=HashAlgorithm.SHA256))
    assert verify_with(public, signed) is True
    signed["msg"] = "hellp"
    assert verify_with(public, signed) is False


@pytest.mark.parametrize("damage", [
    lambda block: block,
    lambda block: block.replace("\n", "\r\n"),
    lambda block: "text before\n" + block + "text after",
    lambda block: block.replace("=cz/W\n", ""),
])
def test_block_signed_by_shap_verifies(damage):
    peer = parse_input(SHAP_SIGN_KEY, WANT_PUB, ALG_PGP_SIGN)
    envelope = parse_input(damage(SHAP_SIGNED), WANT_SIGNATURE)
    assert envelope["msg"] == "pp"
    assert verify_with(peer, envelope) is True


def test_changed_block_signed_by_shap_fails():
    peer = parse_input(SHAP_SIGN_KEY, WANT_PUB, ALG_PGP_SIGN)
    envelope = parse_input(SHAP_SIGNED.replace("\npp\n", "\npq\n"), WANT_SIGNATURE)
    assert envelope["msg"] == "pq"
    assert verify_with(peer, envelope) is False


@pytest.mark.parametrize("want", [WANT_PUB, WANT_ENVELOPE])
def test_signed_block_is_refused_where_it_does_not_belong(want):
    with pytest.raises(MessageCryptoError, match="^not a"):
        parse_input(SHAP_SIGNED, want, ALG_PGP_SIGN)


def _standalone_public(keys, purpose):
    return {"v": 1, "op": "pub", "alg": ALG_PGP_ENCRYPT,
            "armor": str(pgp_ops.key_from_rsa(keys.rsa_encryption_key() if purpose == "encrypt" else keys.rsa_signing_key(), purpose).pubkey)}


def test_pgp_public_key_is_one_block_signing_key_first_encryption_subkey(pgp_keys):
    pgpy, *_rest = pgp_ops._import_pgpy()
    from pgpy.constants import KeyFlags

    key, _others = pgpy.PGPKey.from_blob(export_public(pgp_keys, ALG_PGP_SIGN)["armor"])
    assert len(key.subkeys) == 1
    subkey = next(iter(key.subkeys.values()))
    # The two seed keys keep their own fingerprints, so old messages and signatures still match.
    assert key.fingerprint == pgp_ops.key_from_rsa(pgp_keys.rsa_signing_key(), "sign").fingerprint
    assert subkey.fingerprint == pgp_ops.key_from_rsa(pgp_keys.rsa_encryption_key(), "encrypt").fingerprint
    assert key._get_key_flags() == {KeyFlags.Certify, KeyFlags.Sign}
    assert subkey._get_key_flags() == {KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage}


def test_pgp_public_key_has_no_clock_dates(pgp_keys, monkeypatch):
    first = export_public(pgp_keys, ALG_PGP_SIGN)["armor"]

    class BootClock(pgp_ops.datetime):
        @classmethod
        def now(cls, tz=None):
            return pgp_ops.datetime(1970, 1, 1, 0, 3, 20, tzinfo=tz)

    monkeypatch.setattr(pgp_ops, "datetime", BootClock)
    assert export_public(pgp_keys, ALG_PGP_SIGN)["armor"] == first
    pgpy, *_rest = pgp_ops._import_pgpy()
    key, _others = pgpy.PGPKey.from_blob(first)
    subkey = next(iter(key.subkeys.values()))
    assert {signature.created for signature in subkey.__sig__} == {pgp_ops.KEY_CREATED}


def test_device_to_device_pgp_key_works_for_encrypt_and_verify(pgp_keys):
    shown = export_public(pgp_keys, ALG_PGP_SIGN)
    envelope = encrypt_for(pgp_keys, ALG_PGP_ENCRYPT, shown, "hello")
    assert decrypt_with(pgp_keys, envelope) == "hello"
    assert verify_with(shown, sign_with(pgp_keys, ALG_PGP_SIGN, "hello")) is True


def test_message_to_the_old_encryption_key_still_decrypts(pgp_keys):
    envelope = encrypt_for(pgp_keys, ALG_PGP_ENCRYPT, _standalone_public(pgp_keys, "encrypt"), "older")
    assert decrypt_with(pgp_keys, envelope) == "older"


def test_signing_only_pgp_key_cannot_be_encrypted_to(pgp_keys):
    with pytest.raises(MessageCryptoError, match="can't encrypt"):
        encrypt_for(pgp_keys, ALG_PGP_ENCRYPT, _standalone_public(pgp_keys, "sign"), "hello")


def test_key_type_matching_treats_both_pgp_tags_as_one():
    from seedsigner.message_crypto.codec import same_key_type
    assert same_key_type(ALG_PGP_SIGN, ALG_PGP_ENCRYPT)
    assert same_key_type(ALG_PGP_ENCRYPT, ALG_PGP_SIGN)
    assert same_key_type(ALG_RSA_SIGN, ALG_RSA_SIGN)
    assert not same_key_type(ALG_RSA_SIGN, ALG_RSA_ENCRYPT)
    assert not same_key_type(ALG_PGP_SIGN, ALG_RSA_SIGN)
