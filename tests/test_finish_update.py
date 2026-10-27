from pathlib import Path

from pmkt_alert.updater import finish_update


class Fake:
    def __init__(self, copy_fails=0):
        self.calls, self.copy_fails = [], copy_fails

    def wait(self, pid, timeout):
        self.calls.append(("wait", pid))

    def copy(self, src, dst):
        if self.copy_fails:
            self.copy_fails -= 1
            raise PermissionError("locked")
        self.calls.append(("copy", Path(src).name, Path(dst)))

    def launch(self, path):
        self.calls.append(("launch", Path(path)))

    def unlink(self, path):
        self.calls.append(("unlink", Path(path)))

    def sleep(self, s):
        self.calls.append(("sleep", s))


def _run(f, old, tries=30):
    return finish_update(Path(old), 123, me=Path("/u/updates/PMKT-Alert.exe"), wait_fn=f.wait, copy_fn=f.copy,
                         launch_fn=f.launch, unlink_fn=f.unlink, sleep_fn=f.sleep, tries=tries, log=lambda m: None)


def test_waits_copies_renames_and_launches():
    f = Fake()
    out = _run(f, "/d/PMKT-Alert-v0.1.2.exe")
    assert f.calls[0] == ("wait", 123)
    assert ("copy", "PMKT-Alert.exe", Path("/d/PMKT-Alert.exe")) in f.calls
    assert ("unlink", Path("/d/PMKT-Alert-v0.1.2.exe")) in f.calls and f.calls[-1] == ("launch", Path("/d/PMKT-Alert.exe"))
    assert out == Path("/d/PMKT-Alert.exe")


def test_retries_while_locked():
    f = Fake(copy_fails=3)
    _run(f, "/d/PMKT-Alert.exe")
    assert [c for c in f.calls if c[0] == "sleep"] == [("sleep", 1)] * 3
    assert not any(c[0] == "unlink" for c in f.calls)  # same name: nothing to remove
    assert f.calls[-1] == ("launch", Path("/d/PMKT-Alert.exe"))


def test_gives_up_and_reopens_old_app():
    f = Fake(copy_fails=99)
    out = _run(f, "/d/PMKT-Alert-v0.1.2.exe", tries=5)
    assert out == Path("/d/PMKT-Alert-v0.1.2.exe") and f.calls[-1] == ("launch", Path("/d/PMKT-Alert-v0.1.2.exe"))
    assert not any(c[0] == "unlink" for c in f.calls)
