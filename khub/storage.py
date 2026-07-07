import hashlib
import os
import shutil


class ManagedLibrary:
    """受管库目录：原文件按 sha256 分桶落盘，天然去重。二进制不进 SQLite。"""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    @staticmethod
    def _sha256(path, chunk_size=1 << 20):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(chunk_size), b""):
                h.update(chunk)
        return h.hexdigest()

    def store(self, src_path, move=False):
        sha = self._sha256(src_path)
        ext = os.path.splitext(src_path)[1].lower()
        dest_dir = os.path.join(self.root, sha[:2])
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, sha + ext)
        src_abs = os.path.abspath(src_path)
        dest_abs = os.path.abspath(dest)
        if not os.path.exists(dest):
            if move:
                shutil.move(src_abs, dest_abs)
            else:
                shutil.copy2(src_abs, dest_abs)
        elif move and src_abs != dest_abs:
            os.remove(src_abs)
        size = os.path.getsize(dest_abs)
        return sha, dest_abs, size

    def path_for_hash(self, sha, ext=""):
        return os.path.join(self.root, sha[:2], sha + ext)
