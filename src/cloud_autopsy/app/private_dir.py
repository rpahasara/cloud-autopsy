"""Private local directories for generated secrets (grant tokens), outside any Git working tree.

- **POSIX:** created with mode 0700, and the mode is re-checked after creation.
- **Windows:** inherited permissions are removed and the current user and SYSTEM are granted by SID.
  The resulting DACL is read back as SDDL and must be protected and allow only the current user,
  SYSTEM, Administrators and OWNER RIGHTS. Python 3.13 itself creates private temporary directories
  with Administrators and OWNER RIGHTS, the Windows equivalent of an owner-only directory. Users,
  Everyone, Authenticated Users or any other trustee causes a refusal.
  ``icacls.exe`` is called from ``%SystemRoot%\\System32``, never through ``PATH``.

On any failure the directory is removed again and the caller gets an error; secrets are never
written into a directory whose protection could not be confirmed.
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"
OWNER_RIGHTS_SID = "S-1-3-4"
_SID = re.compile(r"S-1-[0-9]{1,13}(?:-[0-9]{1,10}){1,15}", re.ASCII)  # local, domain or Entra ID accounts


class PrivateDirError(RuntimeError):
    pass


def _inside_git_tree(path):
    return any((parent / ".git").exists() for parent in [path, *path.parents])


def _system32(name):
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return str(Path(root) / "System32" / name)


def _current_sid():
    out = subprocess.run([_system32("whoami.exe"), "/user", "/fo", "csv", "/nh"], check=True,
                         capture_output=True, text=True, timeout=30).stdout
    found = _SID.findall(out)
    if len(found) != 1:
        raise PrivateDirError("could not determine the current user's SID")
    return found[0]


def _restrict_windows(directory):
    sid = _current_sid()
    icacls = _system32("icacls.exe")
    subprocess.run([icacls, str(directory), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F",
                    f"*{SYSTEM_SID}:(OI)(CI)F"], check=True, capture_output=True, timeout=30)
    trustees = _dacl_trustees(directory, icacls)
    allowed = {sid, SYSTEM_SID, "SY", "BA", ADMINISTRATORS_SID, "OW", OWNER_RIGHTS_SID}
    if not trustees or not trustees <= allowed or sid not in trustees:
        raise PrivateDirError("the directory ACL grants access beyond the current user, SYSTEM and Administrators")


def _dacl_trustees(directory, icacls):
    """Trustee SIDs of the directory's DACL, read as SDDL; the DACL must be protected and allow-only."""
    saved = directory / ".acl-check"
    try:
        subprocess.run([icacls, str(directory), "/save", str(saved)], check=True, capture_output=True, timeout=30)
        sddl = saved.read_bytes().decode("utf-16-le", "replace")
    finally:
        saved.unlink(missing_ok=True)
    dacl = re.search(r"D:([A-Z]*)((?:\([^)]*\))+)", sddl)
    if not dacl or "P" not in dacl.group(1):
        raise PrivateDirError("the directory DACL is not protected from inheritance")
    trustees = set()
    for ace in re.findall(r"\(([^)]*)\)", dacl.group(2)):
        parts = ace.split(";")
        if len(parts) < 6 or parts[0] != "A":
            raise PrivateDirError("the directory DACL has a non-allow entry")
        trustees.add(parts[5])
    return trustees


def make_private_dir(path=None, prefix="ca-private-"):
    """Create a new private directory (a fresh temporary one when ``path`` is None) and return it."""
    if path is None:
        directory = Path(tempfile.mkdtemp(prefix=prefix))  # 0700 on POSIX
    else:
        directory = Path(os.path.abspath(path))
        if _inside_git_tree(directory):  # refused before anything is created
            raise PrivateDirError("secrets must be written outside any Git working tree")
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        if _inside_git_tree(directory):
            raise PrivateDirError("secrets must be written outside any Git working tree")
        if os.name == "nt":
            _restrict_windows(directory)
        else:
            os.chmod(directory, 0o700)
            if stat.S_IMODE(os.stat(directory).st_mode) != 0o700:
                raise PrivateDirError("could not restrict the directory to its owner")
    except (OSError, subprocess.SubprocessError, PrivateDirError) as exc:
        shutil.rmtree(directory, ignore_errors=True)
        if isinstance(exc, PrivateDirError):
            raise
        raise PrivateDirError(f"could not create a private directory ({type(exc).__name__})") from None
    return directory
