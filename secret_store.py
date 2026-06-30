"""Windows DPAPI 기반 비밀값 암호화 저장 헬퍼.

- DPAPI(CryptProtectData)로 *현재 Windows 사용자 계정*에 묶어 암호화한다.
- 마스터 비밀번호 없이 복호화되므로 무인 데몬에서도 그대로 동작한다.
- 추가 의존성 없음 (ctypes 로 crypt32.dll 직접 호출).
- 같은 평문도 매번 다른 암호문이 된다(DPAPI 내부 랜덤화 + 앱 고유 entropy).

저장 규약: 환경변수 NAME 은 평문, NAME_ENC 는 base64(DPAPI blob).
  resolve_secret("ECFS_CERT_PW") -> ECFS_CERT_PW_ENC 우선 복호화, 없으면 ECFS_CERT_PW.

CLI:
  python secret_store.py encrypt-env   # 평문을 환경변수 _ECOURT_SECRET_IN 로 받아 암호문(base64) 출력
  python secret_store.py decrypt        # stdin 의 base64 를 평문으로 출력
  python secret_store.py selftest       # 왕복 검증
"""
import base64
import os
import sys

ENTROPY = b"ecourt-cli/dpapi/v1"

try:
    import ctypes
    from ctypes import wintypes
    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    _PBLOB = ctypes.POINTER(_BLOB)
    _crypt32.CryptProtectData.argtypes = [
        _PBLOB, wintypes.LPCWSTR, _PBLOB, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, _PBLOB]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        _PBLOB, ctypes.c_void_p, _PBLOB, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, _PBLOB]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _HAVE_DPAPI = True
except Exception:
    _HAVE_DPAPI = False

CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _to_blob(data):
    buf = ctypes.create_string_buffer(bytes(data), max(len(data), 1))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _read_out(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect(plaintext, entropy=ENTROPY):
    if not _HAVE_DPAPI:
        raise RuntimeError("DPAPI 사용 불가 (Windows 전용)")
    blob_in, _b1 = _to_blob(plaintext.encode("utf-8"))
    ent, _b2 = _to_blob(entropy)
    out = _BLOB()
    if not _crypt32.CryptProtectData(ctypes.byref(blob_in), None,
            ctypes.byref(ent), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    return base64.b64encode(_read_out(out)).decode("ascii")


def unprotect(b64, entropy=ENTROPY):
    if not _HAVE_DPAPI:
        raise RuntimeError("DPAPI 사용 불가 (Windows 전용)")
    blob_in, _b1 = _to_blob(base64.b64decode(b64))
    ent, _b2 = _to_blob(entropy)
    out = _BLOB()
    if not _crypt32.CryptUnprotectData(ctypes.byref(blob_in), None,
            ctypes.byref(ent), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    return _read_out(out).decode("utf-8")


def resolve_secret(name):
    """NAME_ENC(암호문) 우선 복호화, 없으면 NAME(평문) 반환."""
    enc = os.getenv(name + "_ENC")
    if enc:
        try:
            return unprotect(enc)
        except Exception as e:
            print(f"[secret] {name}_ENC 복호화 실패: {e}", file=sys.stderr)
    return os.getenv(name)


def _main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "encrypt-env":
        val = os.environ.get("_ECOURT_SECRET_IN", "")
        if val == "":
            return 0
        sys.stdout.write(protect(val))
    elif cmd == "encrypt":
        sys.stdout.write(protect(sys.stdin.read().rstrip("\r\n")))
    elif cmd == "decrypt":
        sys.stdout.write(unprotect(sys.stdin.read().strip()))
    elif cmd == "selftest":
        s = "테스트@Pass!#123 한글"
        ok = unprotect(protect(s)) == s
        diff = protect(s) != protect(s)  # 매번 달라야 함
        print(f"roundtrip={'OK' if ok else 'FAIL'} randomized={'OK' if diff else 'FAIL'}")
        return 0 if (ok and diff) else 1
    else:
        sys.stderr.write("usage: secret_store.py encrypt-env|encrypt|decrypt|selftest\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
