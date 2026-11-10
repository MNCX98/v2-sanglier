"""Tests ciblés sur les confirmations de position et de déplacement."""
from types import SimpleNamespace
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phases.p4_tour as p4
from core.combat import Fighter
from core.grid import to_screen


class FakeCapture:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def grab(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame, (0, 0)


def _clock(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr(p4.time, "time", lambda: next(it, values[-1]))
    monkeypatch.setattr(p4.time, "sleep", lambda _seconds: None)


def test_green_zone_center_uses_grid_median(monkeypatch):
    ref = (900, 500)
    expected = to_screen((3, -2), ref)
    cells = [to_screen((u, v), ref)
             for u in range(1, 6) for v in range(-4, 1)
             if abs(u - 3) + abs(v + 2) <= 3]
    monkeypatch.setattr(p4, "reachable_cells", lambda _scene, _ref: cells)
    got = p4._green_zone_center(np.zeros((1020, 1920, 3), np.uint8), [Fighter(*ref, 200)])
    assert got == expected


def test_wait_moved_requires_two_consistent_red_ring_detections(monkeypatch):
    start, destination = (800, 600), (888, 622)
    frames = [np.zeros((2, 2, 3), np.uint8) for _ in range(3)]
    ctx = SimpleNamespace(capture=FakeCapture(frames))
    detections = iter([Fighter(*destination, 200), Fighter(*destination, 200)])
    monkeypatch.setattr(p4, "find_me", lambda *_args: next(detections, None))
    monkeypatch.setattr(p4, "_green_zone_center", lambda *_args: None)
    _clock(monkeypatch, [0.0, 0.1, 0.2, 6.0])
    status, pos = p4._wait_moved(ctx, start, expected=destination, timeout=5.0)
    assert status == "moved"
    assert pos == destination


def test_wait_moved_does_not_call_one_red_detection_a_success(monkeypatch):
    start, destination = (800, 600), (888, 622)
    frames = [np.zeros((2, 2, 3), np.uint8) for _ in range(3)]
    ctx = SimpleNamespace(capture=FakeCapture(frames))
    detections = iter([Fighter(*destination, 200), None, None])
    monkeypatch.setattr(p4, "find_me", lambda *_args: next(detections, None))
    monkeypatch.setattr(p4, "_green_zone_center", lambda *_args: None)
    _clock(monkeypatch, [0.0, 0.1, 0.2, 6.0])
    status, pos = p4._wait_moved(ctx, start, expected=destination, timeout=5.0)
    assert status == "unknown"
    assert pos is None


def test_wait_moved_can_confirm_with_stable_green_zone(monkeypatch):
    ref = (900, 500)
    start, destination = to_screen((2, -3), ref), to_screen((5, -3), ref)
    frames = [np.zeros((2, 2, 3), np.uint8) for _ in range(3)]
    ctx = SimpleNamespace(capture=FakeCapture(frames))
    monkeypatch.setattr(p4, "find_me", lambda *_args: None)
    green = iter([destination, destination])
    monkeypatch.setattr(p4, "_green_zone_center", lambda *_args: next(green, destination))
    _clock(monkeypatch, [0.0, 0.1, 0.2, 6.0])
    status, pos = p4._wait_moved(ctx, start, expected=destination, enemies=[Fighter(900, 500, 200)],
                                 before_green=start, timeout=5.0)
    assert status == "moved_green"
    assert pos == destination


def test_move_closer_does_not_click_another_cell_when_result_is_uncertain(monkeypatch):
    clicks = []
    scene = np.zeros((1020, 1920, 3), np.uint8)
    ctx = SimpleNamespace(
        move_uncertain=False,
        failed_moves=[],
        config=SimpleNamespace(click_interval_ms=0, save_diagnostics=False),
        capture=FakeCapture([scene]),
        log=lambda _message: None,
    )
    enemy = Fighter(1000, 600, 200)
    monkeypatch.setattr(p4, "_deselect_spell", lambda _ctx: True)
    monkeypatch.setattr(p4, "plan_move_green", lambda *_args: (enemy, [(900, 600)]))
    monkeypatch.setattr(p4, "_green_zone_center", lambda *_args: None)
    monkeypatch.setattr(p4, "_wait_moved", lambda *_args, **_kwargs: ("unknown", None))
    monkeypatch.setattr(p4.inp, "click", lambda x, y: clicks.append((x, y)))
    monkeypatch.setattr(p4.time, "sleep", lambda _seconds: None)
    ok = p4.move_closer(ctx, [enemy], (800, 600), lambda: False)
    assert not ok
    assert ctx.move_uncertain
    assert len(clicks) == 2  # uniquement le double-clic initial, aucun autre candidat
    assert ctx.failed_moves == []


def test_wait_moved_compensates_green_zone_bias_measured_before_click(monkeypatch):
    """Le centre vert est décalé d'une case par les obstacles : on réutilise le biais initial."""
    ref = (1000, 600)
    start = to_screen((2, -3), ref)
    destination = to_screen((5, -3), ref)
    # Avant le clic, le centre de la zone verte est décalé d'une case en u.
    before_green = to_screen((3, -3), ref)
    after_green = to_screen((6, -3), ref)
    frames = [np.zeros((2, 2, 3), np.uint8) for _ in range(3)]
    ctx = SimpleNamespace(capture=FakeCapture(frames))
    monkeypatch.setattr(p4, "find_me", lambda *_args: None)
    green = iter([after_green, after_green])
    monkeypatch.setattr(p4, "_green_zone_center", lambda *_args: next(green, after_green))
    _clock(monkeypatch, [0.0, 0.1, 0.2, 6.0])
    status, pos = p4._wait_moved(ctx, start, expected=destination,
                                 enemies=[Fighter(*ref, 200)], before_green=before_green, timeout=5.0)
    assert status == "moved_green"
    assert pos == destination


def test_wait_moved_does_not_confirm_green_center_without_calibration(monkeypatch):
    start, destination = (800, 600), (888, 622)
    frames = [np.zeros((2, 2, 3), np.uint8) for _ in range(3)]
    ctx = SimpleNamespace(capture=FakeCapture(frames))
    monkeypatch.setattr(p4, "find_me", lambda *_args: None)
    green = iter([destination, destination])
    monkeypatch.setattr(p4, "_green_zone_center", lambda *_args: next(green, destination))
    _clock(monkeypatch, [0.0, 0.1, 0.2, 6.0])
    status, pos = p4._wait_moved(ctx, start, expected=destination,
                                 enemies=[Fighter(900, 500, 200)], before_green=None, timeout=5.0)
    assert status == "unknown"
    assert pos is None
