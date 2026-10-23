"""The run engine: cutting a run's output, its levels, the queue, Stop, and
finding again the runs a closed window left going."""
import json
import os
import sys
import time

from pca2dgui import runner


def test_cut_output_keeps_bars_apart_from_lines():
    segments, rest = runner.cut_output("a\nbar 1\rbar 2\rdone\nhalf")
    assert segments == [("a", False), ("bar 1", True), ("bar 2", True),
                        ("done", False)]
    assert rest == "half"
    segments, rest = runner.cut_output("x\r\ny\n")
    assert segments == [("x", False), ("y", False)] and rest == ""


def test_levels_from_colours_and_markers():
    assert runner.level_of("\x1b[92;1mstage cube\x1b[0;0m") == "info"
    assert runner.level_of("\x1b[94;1mvalue\x1b[0;0m") == "value"
    assert runner.level_of("\x1b[93;1mhm\x1b[0;0m") == "warn"
    assert runner.level_of("\x1b[91mbad\x1b[0m") == "error"
    assert runner.level_of("2026-10-23 12:00:00.000|W| plain") == "warn"
    assert runner.level_of("nothing") == "plain"


def test_a_bar_replaces_itself_and_the_stage_is_followed(tmp_path):
    job = runner.Job("j", "j", str(tmp_path), "w.py", sys.executable,
                     str(tmp_path), {})
    job.add("", True)                         # the lone \r a bar starts with
    job.add(" 1/3", True)
    job.add(" 2/3", True)
    job.add(" 3/3", False)
    job.add("2026-10-23 12:00:00.000|I| \tLBL Compute", False)
    job.add("x|G| stage fit", False)
    job.add("tellu-cleaning E2DS for file 7 of 39", False)
    ops = [(e["op"], e["text"]) for e in job.events]
    assert ops[:3] == [("add", " 1/3"), ("replace", " 2/3"),
                       ("replace", " 3/3")]
    assert job.stage == "PCA2D fit"
    assert job.counter == "7 / 39"


def _wrap(tmp_path, body):
    path = tmp_path / "wrap.py"
    path.write_text(body)
    return str(path)


def _wait(job, states=("done", "failed", "stopped"), timeout=30):
    end = time.time() + timeout
    while job.state not in states and time.time() < end:
        time.sleep(0.1)
    return job.state


def test_a_run_its_log_and_its_exit_code(tmp_path):
    queue = runner.Runner()
    wrap = _wrap(tmp_path, "print('\\x1b[92mhello\\x1b[0m')\nraise SystemExit(3)\n")
    job = queue.submit("x", str(tmp_path), wrap, sys.executable,
                       str(tmp_path), {})
    assert _wait(job) == "failed" and job.exit == 3
    assert "hello" in (tmp_path / "run.log").read_text()
    record = json.loads((tmp_path / "run.json").read_text())
    assert record["state"] == "failed" and record["exit"] == 3


def test_runs_go_one_at_a_time_and_stop_stops(tmp_path):
    queue = runner.Runner()
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    slow = _wrap(first, "import time\nprint('start', flush=True)\n"
                        "time.sleep(60)\n")
    quick = _wrap(second, "print('quick')\n")
    one = queue.submit("one", str(first), slow, sys.executable,
                       str(tmp_path), {})
    two = queue.submit("two", str(second), quick, sys.executable,
                       str(tmp_path), {})
    assert _wait(one, ("running",)) == "running"
    time.sleep(0.5)
    assert two.state == "queued"
    assert queue.stop(one.id)
    assert _wait(one) == "stopped"
    assert _wait(two) == "done"


def test_a_closed_window_finds_its_runs_again(tmp_path):
    runs = tmp_path / "gui" / "runs"
    gone = runs / "a"
    gone.mkdir(parents=True)
    (gone / "run.raw").write_text("\x1b[92mfinished meanwhile\x1b[0m\n")
    (gone / "exit").write_text("0\n")
    (gone / "run.json").write_text(json.dumps(dict(
        id="a", name="a", state="running", folder=str(gone),
        wrap=str(gone / "wrap.py"), pid=999999999, created=1.0,
        started=1.0)))
    waiting = runs / "b"
    waiting.mkdir()
    _wrap(waiting, "print('later')\n")
    (waiting / "run.json").write_text(json.dumps(dict(
        id="b", name="b", state="queued", folder=str(waiting),
        wrap=str(waiting / "wrap.py"), python=sys.executable, created=2.0)))
    queue = runner.Runner()
    queue.adopt(str(tmp_path), os.path.join("gui", "runs"))
    first, second = queue.get("a"), queue.get("b")
    assert _wait(first) == "done"
    assert any("finished meanwhile" in e["text"] for e in first.events)
    assert _wait(second) == "done"
