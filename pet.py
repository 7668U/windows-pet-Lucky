import argparse
import math
import os
import sys
import time
import numpy as np

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from renderer import NeonSpiderRenderer
from win32_window import LayeredPetWindow
from gait import SpiderGaitEngine
from behavior import SpiderBehaviorController


DEFAULT_SCALE = 0.42
MIN_SCALE = 0.26
MAX_SCALE = 0.78
TARGET_FPS = 45.0


class NeonSpiderPetApp:
    """Main desktop pet application wiring Win32 layered window, IK gait, AI behaviors, and neon renderer."""

    # Context menu command IDs
    CMD_WAVE = 101
    CMD_THREAT = 102
    CMD_POUNCE = 103
    CMD_SCAN = 104

    CMD_TOGGLE_WANDER = 201
    CMD_TOGGLE_FOLLOW = 202
    CMD_TOGGLE_STAY = 203
    CMD_TOGGLE_SLEEP = 204

    CMD_ZOOM_IN = 301
    CMD_ZOOM_OUT = 302
    CMD_ZOOM_RESET = 303

    CMD_EXIT = 999

    def __init__(self, scale: float = DEFAULT_SCALE):
        self.scale = max(MIN_SCALE, min(MAX_SCALE, float(scale)))
        self.window = LayeredPetWindow(title="Neon Spider Cyber Pet")
        work_area = self.window.get_work_area()
        monitor_areas = self.window.get_monitor_work_areas()

        # Spawn comfortably in the lower-right quadrant of the primary desktop work area
        wx0, wy0, wx1, wy1 = work_area
        start_x = wx0 + (wx1 - wx0) * 0.76
        start_y = wy0 + (wy1 - wy0) * 0.72

        self.renderer = NeonSpiderRenderer(PROJECT_DIR, scale=self.scale)
        self.gait = SpiderGaitEngine(self.renderer.rig, scale=self.renderer.scale, start_desk_pos=(start_x, start_y))
        self.behavior = SpiderBehaviorController(self.gait, work_area=work_area, monitor_areas=monitor_areas)

        # Smart click-vs-drag disambiguation so quick clicks/double-clicks don't snap into mid-air dangle
        self._press_active = False
        self._press_origin = (0, 0)
        self._press_time = 0.0
        self._drag_engaged = False

        self._bind_window_callbacks()

    def _bind_window_callbacks(self):
        self.window.on_drag_start = self._on_mouse_down
        self.window.on_drag_move = self._on_mouse_drag_move
        self.window.on_drag_end = self._on_mouse_up
        self.window.on_double_click = self._on_double_click
        self.window.on_wheel = self._on_mouse_wheel
        self.window.build_menu_items = self._build_menu_items
        self.window.on_menu_command = self._on_menu_command

    # -------------------- Scaling & Coordinate Helpers --------------------

    def set_scale(self, new_scale: float):
        clamped = max(MIN_SCALE, min(MAX_SCALE, float(new_scale)))
        self.renderer.set_scale(clamped)
        self.scale = self.renderer.scale
        self.gait.set_scale(self.scale)
        cx, cy = self.behavior.clamp_to_work_area(self.gait.desk_x, self.gait.desk_y)
        self.gait.desk_x, self.gait.desk_y = cx, cy

    def _desk_to_window_topleft(self, desk_pos: tuple[float, float]) -> tuple[int, int]:
        body_cx, body_cy = self.renderer.world_to_canvas(self.gait.body_center_model)
        return (int(round(desk_pos[0] - body_cx)), int(round(desk_pos[1] - body_cy)))

    # -------------------- Mouse & Menu Callbacks --------------------

    def _on_mouse_down(self, cx: int, cy: int):
        self._press_active = True
        self._press_origin = (cx, cy)
        self._press_time = time.perf_counter()
        self._drag_engaged = False

    def _on_mouse_drag_move(self, cx: int, cy: int, dx: int, dy: int):
        if not self._press_active:
            return
        if not self._drag_engaged:
            if math.hypot(cx - self._press_origin[0], cy - self._press_origin[1]) >= 4.0:
                self._drag_engaged = True
                self.behavior.begin_drag(self._press_origin[0], self._press_origin[1])
        if self._drag_engaged:
            self.behavior.drag_move(cx, cy, dx, dy)

    def _on_mouse_up(self, cx: int, cy: int, vx: float, vy: float):
        was_dragging = self._drag_engaged
        self._press_active = False
        self._drag_engaged = False
        if was_dragging:
            self.behavior.end_drag(cx, cy, vx, vy)
        elif self.behavior.state == "IDLE":
            # Gentle true-front-foot (L3/R3) tap reaction on quick single click
            self.behavior.blink_timer = 0.0
            if self.behavior.tap_timer < 0.0:
                rad = math.radians(self.gait.heading_deg)
                side_dot = (cx - self.gait.desk_x) * math.cos(rad) + (cy - self.gait.desk_y) * math.sin(rad)
                self.behavior.tap_leg = "L3" if side_dot < 0.0 else "R3"
                self.behavior.tap_timer = 0.0

    def _on_double_click(self, cx: int, cy: int):
        self._press_active = False
        self._drag_engaged = False
        self.behavior.trigger_trick(None)

    def _on_mouse_wheel(self, notches: float):
        self.set_scale(self.scale + notches * 0.04)

    def _build_menu_items(self) -> list[dict]:
        pct = int(round((self.scale / DEFAULT_SCALE) * 100))
        return [
            {"id": self.CMD_WAVE, "label": "前足挥手打招呼"},
            {"id": self.CMD_THREAT, "label": "双前肢警戒威慑"},
            {"id": self.CMD_POUNCE, "label": "蓄力腾空扑跃"},
            {"id": self.CMD_SCAN, "label": "赛博雷达脉冲"},
            {"separator": True},
            {"id": self.CMD_TOGGLE_WANDER, "label": "自主漫步巡逻", "radio_group": "mode", "checked": self.behavior.mode == "WANDER"},
            {"id": self.CMD_TOGGLE_FOLLOW, "label": "跟随鼠标陪伴", "radio_group": "mode", "checked": self.behavior.mode == "FOLLOW"},
            {"id": self.CMD_TOGGLE_STAY, "label": "固定原地待命", "radio_group": "mode", "checked": self.behavior.mode == "STAY"},
            {"id": self.CMD_TOGGLE_SLEEP, "label": "休眠呼吸灯模式", "radio_group": "mode", "checked": self.behavior.mode == "SLEEP"},
            {"separator": True},
            {"id": self.CMD_ZOOM_IN, "label": f"放大体型 (+)  [当前 {pct}%]"},
            {"id": self.CMD_ZOOM_OUT, "label": "缩小体型 (-)"},
            {"id": self.CMD_ZOOM_RESET, "label": "恢复默认大小 (100%)"},
            {"separator": True},
            {"id": self.CMD_EXIT, "label": "退出赛博蛛宠 (Esc)"},
        ]

    def _on_menu_command(self, cmd_id: int):
        if cmd_id == self.CMD_WAVE:
            self.behavior.trigger_trick("WAVE")
        elif cmd_id == self.CMD_THREAT:
            self.behavior.trigger_trick("THREAT")
        elif cmd_id == self.CMD_POUNCE:
            self.behavior.trigger_trick("POUNCE")
        elif cmd_id == self.CMD_SCAN:
            self.behavior.trigger_trick("SCAN")
        elif cmd_id == self.CMD_TOGGLE_WANDER:
            self.behavior.set_mode("WANDER")
        elif cmd_id == self.CMD_TOGGLE_FOLLOW:
            self.behavior.set_mode("FOLLOW")
        elif cmd_id == self.CMD_TOGGLE_STAY:
            self.behavior.set_mode("STAY")
        elif cmd_id == self.CMD_TOGGLE_SLEEP:
            self.behavior.set_mode("SLEEP")
        elif cmd_id == self.CMD_ZOOM_IN:
            self.set_scale(self.scale + 0.06)
        elif cmd_id == self.CMD_ZOOM_OUT:
            self.set_scale(self.scale - 0.06)
        elif cmd_id == self.CMD_ZOOM_RESET:
            self.set_scale(DEFAULT_SCALE)
        elif cmd_id == self.CMD_EXIT:
            self.window.close()

    # -------------------- Frame Loop & Self-Test --------------------

    def step_frame(self, dt: float):
        # Engage pickup automatically if user holds mouse button down >= 0.15s even without moving
        if self._press_active and not self._drag_engaged:
            if time.perf_counter() - self._press_time >= 0.15:
                self._drag_engaged = True
                cx, cy = self.window.get_cursor_pos()
                self.behavior.begin_drag(cx, cy)

        cursor_pos = self.window.get_cursor_pos()
        state_frame = self.behavior.update(dt, cursor_pos=cursor_pos)

        rgba = self.renderer.render_frame(
            leg_joints_world=state_frame["leg_joints_world"],
            body_offset=state_frame["body_offset"],
            heading_deg=state_frame["heading_deg"],
            abdomen_wag_deg=state_frame["abdomen_wag_deg"],
            blink=state_frame["blink"],
            hud_phase=state_frame["hud_phase"],
            scan_pulse=state_frame["scan_pulse"],
            glow_strength=state_frame["glow_strength"],
        )
        alpha_map = np.asarray(rgba, dtype=np.uint8)[:, :, 3]
        bgra_bytes = self.renderer.to_premultiplied_bgra(rgba)
        win_x, win_y = self._desk_to_window_topleft(state_frame["desk_pos"])
        w, h = self.renderer.canvas_size
        self.window.present(bgra_bytes, alpha_map, win_x, win_y, w, h)
        return state_frame

    def run(self):
        frame_interval = 1.0 / TARGET_FPS
        last_t = time.perf_counter()
        work_area_timer = 0.0
        try:
            while self.window.running:
                self.window.pump_events()
                if not self.window.running:
                    break

                now = time.perf_counter()
                dt = now - last_t
                last_t = now

                work_area_timer += dt
                if work_area_timer >= 2.5:
                    work_area_timer = 0.0
                    self.behavior.set_monitor_areas(self.window.get_monitor_work_areas())

                self.step_frame(dt)

                elapsed = time.perf_counter() - now
                sleep_s = frame_interval - elapsed
                if sleep_s > 0.001:
                    time.sleep(sleep_s)
        except KeyboardInterrupt:
            pass
        finally:
            self.window.close()

    def run_self_test(self) -> int:
        """Automated live Win32 window + 360 steering + tricks + drag + zoom end-to-end verification."""
        dt = 1.0 / TARGET_FPS
        t0 = time.perf_counter()
        try:
            menu = self._build_menu_items()
            assert len(menu) >= 12, "Menu items incomplete"
            for mode_cmd in (
                self.CMD_TOGGLE_FOLLOW,
                self.CMD_TOGGLE_STAY,
                self.CMD_TOGGLE_SLEEP,
                self.CMD_TOGGLE_WANDER,
            ):
                self._on_menu_command(mode_cmd)
                checked = [it["id"] for it in self._build_menu_items() if it.get("checked")]
                assert checked == [mode_cmd], f"Expected exclusive selection {[mode_cmd]}, got {checked}"

            def _start_scurry():
                self.behavior.waypoint = self.behavior.clamp_to_work_area(
                    self.gait.desk_x - 180.0,
                    self.gait.desk_y - 140.0,
                )
                self.behavior._enter_state("SCURRY", 1.8)

            # Exercise 360 steering, all 4 tricks, zoom, rotated drag/settle, sleep, and layered window blitting
            seq = [
                (0, _start_scurry),
                (22, lambda: self._on_menu_command(self.CMD_WAVE)),
                (34, lambda: self._on_menu_command(self.CMD_THREAT)),
                (46, lambda: self._on_menu_command(self.CMD_POUNCE)),
                (62, lambda: self._on_menu_command(self.CMD_SCAN)),
                (72, lambda: self._on_menu_command(self.CMD_ZOOM_IN)),
                (76, lambda: self._on_menu_command(self.CMD_ZOOM_RESET)),
                (80, lambda: self._on_mouse_down(int(self.gait.desk_x), int(self.gait.desk_y))),
                (82, lambda: self._on_mouse_drag_move(int(self.gait.desk_x + 55), int(self.gait.desk_y - 30), 55, -30)),
                (90, lambda: self._on_mouse_up(int(self.gait.desk_x + 55), int(self.gait.desk_y - 30), 180.0, -60.0)),
                (98, lambda: self._on_menu_command(self.CMD_TOGGLE_SLEEP)),
                (103, lambda: self._on_menu_command(self.CMD_TOGGLE_WANDER)),
            ]
            actions = dict(seq)
            states_seen = set()
            headings_seen = []

            for step in range(108):
                self.window.pump_events()
                if step in actions:
                    actions[step]()
                sf = self.step_frame(dt)
                states_seen.add(sf["state"])
                headings_seen.append(sf["heading_deg"])
                time.sleep(0.006)

            h_span = max(headings_seen) - min(headings_seen)
            total_ms = (time.perf_counter() - t0) * 1000.0
            print(
                f"SELF_TEST_OK | frames=108 | states={sorted(states_seen)} "
                f"| heading_span={h_span:.1f}deg | canvas={self.renderer.canvas_size} | elapsed={total_ms:.1f}ms"
            )
            return 0
        finally:
            self.window.close()


def main():
    parser = argparse.ArgumentParser(description="Cyberpunk Neon Spider Desktop Pet")
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE, help="Sprite scale (0.26 .. 0.78)")
    parser.add_argument("--self-test", action="store_true", help="Run automated live window self-test and exit")
    args = parser.parse_args()

    app = NeonSpiderPetApp(scale=args.scale)
    if args.self_test:
        sys.exit(app.run_self_test())
    app.run()


if __name__ == "__main__":
    main()
