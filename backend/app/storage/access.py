"""Path policy for automatic imports. The explicit upload path is independent."""

import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.security.file_validation import EXTENSIONS

SUPPORTED_EXTENSIONS = tuple(sorted(EXTENSIONS))
BLOCKED_DIRECTORIES = frozenset({
    "windows", "program files", "program files (x86)", "programdata", "appdata", "system volume information",
    "$recycle.bin", "recovery", "boot", "perflogs", "windowsapps", "node_modules", "site-packages", "__pycache__",
    "chrome", "chromium", "firefox", "mozilla", "opera", "tor browser", "bravesoftware", "browser profiles",
    "user data", "keychains", "credentials", "secrets", "gpg", "ssh", "certificates", "passwords",
})
PRIVATE_TERMS = ("credential", "password", "passwd", "passphrase", "secret", "private_key", "private-key", "recovery_key",
                 "recovery-key", "seed_phrase", "seed-phrase", "token", "bitlocker", "wallet")
PRIVATE_NAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "login data", "cookies", "shadow"})
# Reparse points, cloud recall/offline files, and hidden or system entries.
UNSAFE_ATTRIBUTES = 0x400 | 0x1000 | 0x40000 | 0x400000 | 0x2 | 0x4


def path_key(path: Path) -> str:
    return os.path.normcase(str(path))


def lexical_path(value: str) -> Path:
    if not value or "\0" in value or value.startswith(("\\\\", "//")):
        raise ValueError("invalid_path")
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts
            or any(":" in component or (os.name == "nt" and component.endswith((" ", "."))) for component in path.parts[1:])):
        raise ValueError("invalid_path")
    return path


def safe_entry(info: os.stat_result, *, volume=False) -> bool:
    blocked = UNSAFE_ATTRIBUTES & ~0x6 if volume else UNSAFE_ATTRIBUTES
    return not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & blocked


def checked_info(path: Path) -> os.stat_result:
    """Reject symlinks and junctions at every component, including the root."""
    for component in reversed(path.parents):
        info = component.lstat()
        if not safe_entry(info, volume=component.parent == component) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("protected_path")
    info = path.lstat()
    if not safe_entry(info, volume=path.parent == path):
        raise ValueError("protected_path")
    return info


def _windows_api():
    import ctypes
    return ctypes.WinDLL("kernel32", use_last_error=True)


def fixed_drives() -> tuple[Path, ...]:
    if os.name != "nt":
        return ()
    import ctypes
    from ctypes import wintypes
    kernel = _windows_api()
    kernel.GetLogicalDrives.restype = wintypes.DWORD
    kernel.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    mask = kernel.GetLogicalDrives()
    return tuple(Path(f"{chr(65 + index)}:\\") for index in range(26)
                 if mask & (1 << index) and kernel.GetDriveTypeW(f"{chr(65 + index)}:\\") == 3)


def personal_folders() -> tuple[Path, ...]:
    if os.name != "nt":
        return tuple(Path.home() / name for name in ("Desktop", "Documents", "Downloads", "Pictures"))
    import ctypes
    from ctypes import wintypes
    from uuid import UUID

    get_folder = ctypes.WinDLL("shell32").SHGetKnownFolderPath
    get_folder.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    get_folder.restype = ctypes.c_long
    free = ctypes.WinDLL("ole32").CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    folders = []
    for identifier in ("B4BFCC3A-DB2C-424C-B029-7FE99A87C641", "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
                       "374DE290-123F-4565-9164-39C4925E467B", "33E28130-4E1E-4676-835A-98395C3BC3BB"):
        buffer = ctypes.create_string_buffer(UUID(identifier).bytes_le)
        result = ctypes.c_void_p()
        try:
            if get_folder(buffer, 0, None, ctypes.byref(result)) == 0 and result.value:
                folders.append(Path(ctypes.wstring_at(result.value)))
        finally:
            if result.value:
                free(result)
    return tuple(folders)


def protected_locations() -> tuple[Path, ...]:
    paths = []
    for name in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA"):
        if value := os.environ.get(name):
            try:
                paths.append(lexical_path(value))
            except ValueError:
                continue
    return tuple(paths)


@dataclass(frozen=True)
class PathPolicy:
    roots: tuple[Path, ...]
    exclusions: tuple[Path, ...]
    extensions: frozenset[str]

    def covers(self, path: Path, *, directory: bool = False) -> bool:
        if not any(path.is_relative_to(root) for root in self.roots):
            return False
        if any(path.is_relative_to(item) for item in self.exclusions):
            return False
        names = [name.casefold() for name in path.parts[1:]]
        if any(name.startswith((".", "$")) for name in names):
            return False
        if any(name in BLOCKED_DIRECTORIES for name in (names if directory else names[:-1])):
            return False
        if directory:
            return True
        stem = path.stem.casefold()
        return path.suffix.lower() in self.extensions and stem not in PRIVATE_NAMES and not any(term in stem for term in PRIVATE_TERMS)


def fingerprint(info: os.stat_result) -> tuple[int, int, str]:
    # CPython's Windows stat and fstat can assign different meanings to ctime.
    # Use stable birth time when exposed, and native device/inode on 3.11.
    stamp = getattr(info, "st_birthtime_ns", 0) if os.name == "nt" else info.st_ctime_ns
    return info.st_size, info.st_mtime_ns, f"{info.st_dev}:{info.st_ino}:{stamp}"


def _final_windows_path(fd: int) -> Path:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    final = _windows_api().GetFinalPathNameByHandleW
    final.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32768)
    size = final(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
    if not 0 < size < len(buffer) or not buffer.value.startswith("\\\\?\\"):
        raise ValueError("protected_path")
    return lexical_path(buffer.value[4:])


@contextmanager
def open_approved(path: Path, policy: PathPolicy):
    """Verify the opened object before reading any bytes, including after path races."""
    if not policy.covers(path):
        raise ValueError("protected_path")
    before = checked_info(path)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("protected_path")
    if os.name == "nt":
        handle = path.open("rb")
    else:
        parent = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            handle = os.fdopen(os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent), "rb")
        finally:
            os.close(parent)
    with handle:
        opened = os.fstat(handle.fileno())
        if (not stat.S_ISREG(opened.st_mode) or not safe_entry(opened) or opened.st_nlink != 1
                or fingerprint(opened) != fingerprint(before)):
            raise ValueError("changed_file")
        if os.name == "nt" and path_key(_final_windows_path(handle.fileno())) != path_key(path):
            raise ValueError("protected_path")
        yield handle, opened
