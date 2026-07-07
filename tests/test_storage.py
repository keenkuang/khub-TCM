import hashlib
import os
import tempfile

from khub.storage import ManagedLibrary


def _write(path, data=b"data"):
    with open(path, "wb") as f:
        f.write(data)
    return path


def test_store_copies_and_hashes():
    d = tempfile.mkdtemp()
    src = _write(os.path.join(d, "a.pdf"), b"%PDF-1.4 fake")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    sha, dest, size = lib.store(src)
    assert os.path.exists(dest)
    assert dest.startswith(lib.root)
    assert size == len(b"%PDF-1.4 fake")
    assert sha == hashlib.sha256(b"%PDF-1.4 fake").hexdigest()


def test_dedup_no_duplicate_copy():
    d = tempfile.mkdtemp()
    src = _write(os.path.join(d, "a.pdf"), b"same-content")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    sha1, dest1, _ = lib.store(src)
    sha2, dest2, _ = lib.store(src)
    assert sha1 == sha2 and dest1 == dest2
    files = []
    for _, _, fs in os.walk(lib.root):
        files += fs
    assert len(files) == 1


def test_move_removes_source():
    d = tempfile.mkdtemp()
    src = _write(os.path.join(d, "a.pdf"), b"move-me")
    lib = ManagedLibrary(os.path.join(d, "lib"))
    _, dest, _ = lib.store(src, move=True)
    assert not os.path.exists(src)
    assert os.path.exists(dest)
