import math
import random
from gait import SpiderGaitEngine, shortest_angle_diff_deg, wrap_angle_deg


def _vec_to_heading_deg(dx: float, dy: float) -> float:
    """Convert screen vector (dx, dy) to spider heading_deg (0=+Y down, -90=+X right, +90=-X left, 180=-Y up)."""
    return math.degrees(math.atan2(-float(dx), float(dy)))


class SpiderBehaviorController:
    """
    Autonomous AI & signature tricks state machine for the Neon Spider desktop pet.
    Coordinates SpiderGaitEngine, trick animations, breathing, blinking, and HUD/radar FX.
    """

    TRICK_STATES = ("WAVE", "THREAT", "POUNCE", "SCAN")

    # Gravity-drooped model-space foot hang positions when picked up in mid-air
    DANGLE_HOME_MODEL = {
        "L1": (542.0, 468.0),
        "R1": (1038.0, 468.0),
        "L2": (508.0, 672.0),
        "R2": (1072.0, 672.0),
        "L3": (616.0, 796.0),
        "R3": (964.0, 796.0),
        "L4": (746.0, 606.5),
        "R4": (834.0, 606.5),
    }

    # Per-leg (stiffness, damping, wiggle_phase, max_disp_model) for natural phase lag
    DANGLE_SPRING_SPEC = {
        "L1": (95.0, 10.5, 0.0, 82.0),
        "R1": (95.0, 10.5, 2.7, 82.0),
        "L2": (80.0, 9.8, 1.1, 74.0),
        "R2": (80.0, 9.8, 3.9, 74.0),
        "L3": (68.0, 9.0, 2.2, 65.0),
        "R3": (68.0, 9.0, 5.0, 65.0),
        "L4": (130.0, 14.0, 0.6, 5.0),
        "R4": (130.0, 14.0, 3.4, 5.0),
    }

    def __init__(
        self,
        gait: SpiderGaitEngine,
        work_area: tuple[int, int, int, int] = (0, 0, 1920, 1040),
        seed: int | None = None,
        monitor_areas: list[tuple[int, int, int, int]] | None = None,
    ):
        self.gait = gait
        self.work_area = tuple(work_area)
        self.monitor_areas: list[tuple[int, int, int, int]] = []
        self.set_monitor_areas(monitor_areas if monitor_areas else [self.work_area])
        self.rng = random.Random(seed)

        # Mutually-exclusive behavior mode ("WANDER", "FOLLOW", "STAY", "SLEEP")
        self.mode = "WANDER"
        self._prev_awake_mode = "WANDER"
        self.auto_wander = True
        self.follow_mouse = False
        self.stay_put = False
        self.sleeping = False

        # Core state machine: IDLE, WANDER, SCURRY, FOLLOW, WAVE, THREAT, POUNCE, SCAN, SLEEP, DRAGGED, SETTLING
        self.state = "IDLE"
        self.state_time = 0.0
        self.state_duration = 3.2

        # Ambient animation clocks
        self.clock = 0.0
        self.hud_phase = 0.0
        self.next_blink_in = self.rng.uniform(2.4, 5.2)
        self.blink_timer = -1.0
        self.blink_duration = 0.14

        # Idle micro-behaviors (curious heading glance & true front-foot L3/R3 tap)
        self.heading_deg = wrap_angle_deg(gait.heading_deg)
        self.idle_base_heading_deg = self.heading_deg
        self.idle_glance_deg = 0.0
        self.next_glance_in = 1.8
        self.tap_leg = "R3"
        self.tap_timer = -1.0
        self.next_tap_in = 4.5

        # Locomotion waypoint & smoothed velocity
        self.waypoint = (gait.desk_x, gait.desk_y)
        self.cmd_vx = 0.0
        self.cmd_vy = 0.0

        # Trick parameters
        self.wave_leg = "R3"
        self.pounce_start = (gait.desk_x, gait.desk_y)
        self.pounce_target = (gait.desk_x, gait.desk_y)
        self.pounce_heading_deg = self.heading_deg
        self.pounce_landed = False
        self.scan_base_heading_deg = self.heading_deg

        # Drag pickup & spring-damper dangle physics state (in spider-local rest space)
        self.dangle_home_local = {}
        cx_m, cy_m = gait.body_center_model
        for lid, (fx, fy) in gait.rest_foot_local.items():
            if lid in gait.PALP_LEGS:
                self.dangle_home_local[lid] = (fx, fy)
            else:
                self.dangle_home_local[lid] = (
                    cx_m + (fx - cx_m) * 0.86,
                    cy_m + (fy - cy_m) * 0.86,
                )
        self.drag_grab_offset = (0.0, 0.0)
        self.drag_target_desk = (gait.desk_x, gait.desk_y)
        self.drag_vx = 0.0
        self.drag_vy = 0.0
        self.dangle_springs = {lid: [0.0, 0.0, 0.0, 0.0] for lid in self.dangle_home_local}
        self.settle_start_feet: dict[str, tuple[float, float]] = {}
        self.settle_vel = [0.0, 0.0]
        self.settle_landed = False

        # Smoothed outputs
        self.extra_wag_deg = 0.0
        self.lean_offset = [0.0, 0.0]

    def _steer_heading(self, target_deg: float, max_rate_deg: float, smooth_k: float, dt: float) -> float:
        """Smoothly steer self.heading_deg along shortest 360-deg arc; returns remaining |angle error|."""
        diff = shortest_angle_diff_deg(target_deg, self.heading_deg)
        blend = 1.0 - math.exp(-smooth_k * dt)
        step = diff * blend
        max_step = max_rate_deg * dt
        if abs(step) > max_step:
            step = math.copysign(max_step, step)
        self.heading_deg = wrap_angle_deg(self.heading_deg + step)
        return abs(shortest_angle_diff_deg(target_deg, self.heading_deg))

    def set_work_area(self, work_area: tuple[int, int, int, int] | list[tuple[int, int, int, int]]):
        if work_area and isinstance(work_area[0], (tuple, list)):
            self.set_monitor_areas(work_area)  # type: ignore[arg-type]
        else:
            self.work_area = tuple(work_area)  # type: ignore[arg-type]
            self.monitor_areas = [self.work_area]

    def set_monitor_areas(self, monitor_areas: list[tuple[int, int, int, int]]):
        cleaned = [tuple(int(v) for v in r) for r in monitor_areas if len(r) == 4 and r[2] > r[0] and r[3] > r[1]]
        if cleaned:
            self.monitor_areas = cleaned
            self.work_area = cleaned[0]
        elif self.work_area:
            self.monitor_areas = [self.work_area]

    def _safe_monitor_rects(self) -> list[tuple[float, float, float, float]]:
        """Per-monitor safe rectangles with outer bezel margins but zero-gap bridges across connected seams."""
        areas = self.monitor_areas if self.monitor_areas else [self.work_area]
        m = max(105.0, 315.0 * self.gait.scale)
        rects: list[tuple[float, float, float, float]] = []
        for idx, (x0, y0, x1, y1) in enumerate(areas):
            mx = (x1 - x0) * 0.25 if (x1 - x0) < m * 2 + 20 else m
            my = (y1 - y0) * 0.25 if (y1 - y0) < m * 2 + 20 else m
            sx0, sy0, sx1, sy1 = float(x0) + mx, float(y0) + my, float(x1) - mx, float(y1) - my
            for jdx, (ox0, oy0, ox1, oy1) in enumerate(areas):
                if idx == jdx:
                    continue
                if min(y1, oy1) - max(y0, oy0) > 80:
                    if abs(ox1 - x0) <= 120:
                        sx0 = min(sx0, 0.5 * (x0 + ox1))
                    if abs(ox0 - x1) <= 120:
                        sx1 = max(sx1, 0.5 * (x1 + ox0))
                if min(x1, ox1) - max(x0, ox0) > 80:
                    if abs(oy1 - y0) <= 120:
                        sy0 = min(sy0, 0.5 * (y0 + oy1))
                    if abs(oy0 - y1) <= 120:
                        sy1 = max(sy1, 0.5 * (y1 + oy0))
            if sx1 < sx0:
                mid_x = 0.5 * (x0 + x1)
                sx0 = sx1 = mid_x
            if sy1 < sy0:
                mid_y = 0.5 * (y0 + y1)
                sy0 = sy1 = mid_y
            rects.append((sx0, sy0, sx1, sy1))
        return rects

    def _safe_bounds(self) -> tuple[float, float, float, float]:
        rects = self._safe_monitor_rects()
        return rects[0]

    @staticmethod
    def _closest_rect_idx(rects: list[tuple[float, float, float, float]], x: float, y: float) -> int:
        best_i = 0
        best_d2 = float("inf")
        for i, (rx0, ry0, rx1, ry1) in enumerate(rects):
            cx = max(rx0, min(rx1, x))
            cy = max(ry0, min(ry1, y))
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_i = i
        return best_i

    def clamp_to_work_area(self, x: float, y: float) -> tuple[float, float]:
        rects = self._safe_monitor_rects()
        idx = self._closest_rect_idx(rects, x, y)
        bx0, by0, bx1, by1 = rects[idx]
        return (max(bx0, min(bx1, x)), max(by0, min(by1, y)))

    def _steer_goal_across_monitors(self, tx: float, ty: float) -> tuple[float, float]:
        """Guide cross-monitor paths smoothly through shared seam doorways when monitor heights/widths differ."""
        rects = self._safe_monitor_rects()
        if len(rects) < 2:
            return (tx, ty)
        sx, sy = self.gait.desk_x, self.gait.desk_y
        ci = self._closest_rect_idx(rects, sx, sy)
        ti = self._closest_rect_idx(rects, tx, ty)
        if ci == ti:
            return (tx, ty)
        cr = rects[ci]
        tr = rects[ti]
        # Connected vertical seam (left <-> right monitors)
        if abs(cr[2] - tr[0]) <= 4.0 or abs(cr[0] - tr[2]) <= 4.0:
            going_right = abs(cr[2] - tr[0]) <= 4.0
            seam_x = cr[2] if going_right else cr[0]
            dy0 = max(cr[1], tr[1]) + 8.0
            dy1 = min(cr[3], tr[3]) - 8.0
            if dy0 < dy1:
                u = (seam_x - sx) / (tx - sx) if abs(tx - sx) > 1e-3 else 0.0
                y_cross = sy + (ty - sy) * max(0.0, min(1.0, u))
                if y_cross < dy0 or y_cross > dy1:
                    door_y = max(dy0, min(dy1, y_cross))
                    door_x = seam_x + (18.0 if going_right else -18.0)
                    return (door_x, door_y)
        # Connected horizontal seam (top <-> bottom monitors)
        if abs(cr[3] - tr[1]) <= 4.0 or abs(cr[1] - tr[3]) <= 4.0:
            going_down = abs(cr[3] - tr[1]) <= 4.0
            seam_y = cr[3] if going_down else cr[1]
            dx0 = max(cr[0], tr[0]) + 8.0
            dx1 = min(cr[2], tr[2]) - 8.0
            if dx0 < dx1:
                u = (seam_y - sy) / (ty - sy) if abs(ty - sy) > 1e-3 else 0.0
                x_cross = sx + (tx - sx) * max(0.0, min(1.0, u))
                if x_cross < dx0 or x_cross > dx1:
                    door_x = max(dx0, min(dx1, x_cross))
                    door_y = seam_y + (18.0 if going_down else -18.0)
                    return (door_x, door_y)
        return (tx, ty)

    def _pick_waypoint(self, max_dist: float = 420.0, min_dist: float = 110.0) -> tuple[float, float]:
        rects = self._safe_monitor_rects()
        s_ratio = self.gait.scale / 0.42
        # When multiple monitors are connected, occasionally pick a cross-seam destination on a neighbor screen
        if len(rects) > 1 and self.rng.random() < 0.28:
            ci = self._closest_rect_idx(rects, self.gait.desk_x, self.gait.desk_y)
            other_indices = [i for i in range(len(rects)) if i != ci]
            oi = self.rng.choice(other_indices)
            ox0, oy0, ox1, oy1 = rects[oi]
            near_x = max(ox0, min(ox1, self.gait.desk_x))
            near_y = max(oy0, min(oy1, self.gait.desk_y))
            span = max_dist * 1.15 * s_ratio
            tx = self.rng.uniform(max(ox0, near_x - span), min(ox1, near_x + span))
            ty = self.rng.uniform(max(oy0, near_y - span * 0.8), min(oy1, near_y + span * 0.8))
            if math.hypot(tx - self.gait.desk_x, ty - self.gait.desk_y) >= 55.0:
                return (tx, ty)

        for _ in range(14):
            ang = self.rng.uniform(0.0, math.tau)
            dist = self.rng.uniform(min_dist, max_dist) * s_ratio
            tx = self.gait.desk_x + math.cos(ang) * dist
            ty = self.gait.desk_y + math.sin(ang) * dist * 0.88
            tx, ty = self.clamp_to_work_area(tx, ty)
            if math.hypot(tx - self.gait.desk_x, ty - self.gait.desk_y) >= 45.0:
                return (tx, ty)
        ci = self._closest_rect_idx(rects, self.gait.desk_x, self.gait.desk_y)
        bx0, by0, bx1, by1 = rects[ci]
        return (0.5 * (bx0 + bx1), 0.5 * (by0 + by1))

    # -------------------- Public Action & Drag Triggers --------------------

    def set_mode(self, mode: str):
        """Select exactly one mutually-exclusive behavior mode: 'WANDER', 'FOLLOW', 'STAY', or 'SLEEP'."""
        mode = mode.upper()
        if mode not in ("WANDER", "FOLLOW", "STAY", "SLEEP"):
            return

        was_sleeping = self.sleeping or self.state == "SLEEP"
        if mode != "SLEEP":
            self._prev_awake_mode = mode
        elif self.mode != "SLEEP":
            self._prev_awake_mode = self.mode

        self.mode = mode
        self.auto_wander = mode == "WANDER"
        self.follow_mouse = mode == "FOLLOW"
        self.stay_put = mode == "STAY"
        self.sleeping = mode == "SLEEP"

        if self.state == "DRAGGED":
            return

        if mode == "SLEEP":
            self.cmd_vx = 0.0
            self.cmd_vy = 0.0
            self._enter_state("SLEEP", duration=999999.0)
            return

        if was_sleeping:
            self.gait.reset_feet_to_home(stance_spread=1.0, heading_deg=self.heading_deg)
            self._enter_state("IDLE", duration=self.rng.uniform(2.0, 4.0))
        elif mode == "STAY" and self.state in ("WANDER", "SCURRY", "FOLLOW"):
            self.cmd_vx = 0.0
            self.cmd_vy = 0.0
            self._enter_state("IDLE", duration=self.rng.uniform(2.4, 4.8))
        elif mode == "WANDER" and self.state == "FOLLOW":
            self.cmd_vx = 0.0
            self.cmd_vy = 0.0
            self._enter_state("IDLE", duration=self.rng.uniform(1.6, 3.2))
        elif mode == "FOLLOW" and self.state in ("WANDER", "SCURRY"):
            self._enter_state("IDLE", duration=self.rng.uniform(1.2, 2.5))

    def set_sleep(self, enabled: bool):
        self.set_mode("SLEEP" if enabled else self._prev_awake_mode)

    def begin_drag(self, cursor_x: float, cursor_y: float):
        """Pick up the spider in mid-air at the exact pixel grabbed (zero pop at any 360-deg heading)."""
        if self.sleeping:
            self.set_mode(self._prev_awake_mode)
        self.drag_grab_offset = (self.gait.desk_x - float(cursor_x), self.gait.desk_y - float(cursor_y))
        self.drag_target_desk = (self.gait.desk_x, self.gait.desk_y)
        self.drag_vx = 0.0
        self.drag_vy = 0.0
        self.cmd_vx = 0.0
        self.cmd_vy = 0.0

        # Initialize spring offsets in spider-local space from current world foot positions
        cur_world = self.gait.current_foot_world_positions(heading_deg=self.heading_deg)
        for lid, (hx, hy) in self.dangle_home_local.items():
            _, _, _, max_d = self.DANGLE_SPRING_SPEC[lid]
            lx, ly = self.gait.ik.world_to_model_local(cur_world[lid], heading_deg=self.heading_deg)
            dx = max(-max_d, min(max_d, lx - hx))
            dy = max(-max_d, min(max_d, ly - hy))
            self.dangle_springs[lid] = [dx, dy, 0.0, 0.0]

        self._enter_state("DRAGGED", duration=999999.0)

    def drag_move(self, cursor_x: float, cursor_y: float, dx: float = 0.0, dy: float = 0.0):
        """Update target desktop position while mouse is dragging the spider."""
        if self.state != "DRAGGED":
            self.begin_drag(cursor_x, cursor_y)
        self.drag_target_desk = (
            float(cursor_x) + self.drag_grab_offset[0],
            float(cursor_y) + self.drag_grab_offset[1],
        )

    def end_drag(self, cursor_x: float, cursor_y: float, release_vx: float = 0.0, release_vy: float = 0.0):
        """Release the spider: glide briefly with toss inertia, clamp inside work area, and bounce on landing."""
        if self.state != "DRAGGED":
            return
        self.drag_target_desk = (
            float(cursor_x) + self.drag_grab_offset[0],
            float(cursor_y) + self.drag_grab_offset[1],
        )
        # Snapshot dangling feet in spider-local space for smooth 360-deg settle interpolation
        self.settle_start_feet = {}
        for lid, (hx, hy) in self.dangle_home_local.items():
            sx, sy, _, _ = self.dangle_springs[lid]
            self.settle_start_feet[lid] = (hx + sx, hy + sy)

        cap = 950.0 * (self.gait.scale / 0.42)
        self.settle_vel = [
            max(-cap, min(cap, float(release_vx) * 0.45)),
            max(-cap, min(cap, float(release_vy) * 0.45 + 90.0 * self.gait.scale)),
        ]
        self.settle_landed = False
        self._enter_state("SETTLING", duration=0.46)

    def trigger_trick(self, trick_name: str | None = None):
        """Trigger a signature trick ('WAVE', 'THREAT', 'POUNCE', 'SCAN') or random if None."""
        if self.state == "DRAGGED":
            return
        if self.sleeping:
            self.set_mode(self._prev_awake_mode)
        if trick_name is None:
            pool = ["WAVE", "THREAT", "SCAN"] if self.stay_put else list(self.TRICK_STATES)
            trick_name = self.rng.choice(pool)
        trick_name = trick_name.upper()

        self.cmd_vx = 0.0
        self.cmd_vy = 0.0
        if trick_name == "WAVE":
            self.wave_leg = self.rng.choice(["L3", "R3"])
            self._enter_state("WAVE", duration=1.85)
        elif trick_name == "THREAT":
            self._enter_state("THREAT", duration=1.65)
        elif trick_name == "POUNCE":
            self.pounce_start = (self.gait.desk_x, self.gait.desk_y)
            if self.stay_put:
                self.pounce_target = self.pounce_start
                self.pounce_heading_deg = self.heading_deg
            else:
                # Pick a lively pounce target within +-115 deg of current heading (clamped to work area)
                leap_h = wrap_angle_deg(self.heading_deg + self.rng.uniform(-115.0, 115.0))
                rad = math.radians(leap_h)
                dist = self.rng.uniform(120.0, 205.0) * (self.gait.scale / 0.42)
                tx, ty = self.clamp_to_work_area(
                    self.gait.desk_x - math.sin(rad) * dist,
                    self.gait.desk_y + math.cos(rad) * dist,
                )
                if math.hypot(tx - self.gait.desk_x, ty - self.gait.desk_y) < 35.0:
                    tx, ty = self._pick_waypoint(max_dist=190.0, min_dist=95.0)
                self.pounce_target = (tx, ty)
                dx_p = tx - self.gait.desk_x
                dy_p = ty - self.gait.desk_y
                self.pounce_heading_deg = (
                    _vec_to_heading_deg(dx_p, dy_p) if math.hypot(dx_p, dy_p) > 8.0 else self.heading_deg
                )
            self.pounce_landed = False
            self._enter_state("POUNCE", duration=1.18)
        elif trick_name == "SCAN":
            self.scan_base_heading_deg = self.heading_deg
            self._enter_state("SCAN", duration=1.40)

    def _enter_state(self, new_state: str, duration: float):
        self.state = new_state
        self.state_time = 0.0
        self.state_duration = duration
        self.tap_timer = -1.0
        if new_state == "IDLE":
            self.idle_base_heading_deg = self.heading_deg
            self.idle_glance_deg = 0.0

    def _choose_next_autonomous_state(self):
        if self.sleeping:
            self._enter_state("SLEEP", 999999.0)
            return

        if self.state in ("WANDER", "SCURRY", "FOLLOW", "SETTLING") or self.state in self.TRICK_STATES:
            self._enter_state("IDLE", self.rng.uniform(2.4, 5.2))
            return

        # Transition out of IDLE
        r = self.rng.random()
        if not self.stay_put and self.auto_wander and not self.follow_mouse:
            if r < 0.48:
                self.waypoint = self._pick_waypoint(max_dist=360.0, min_dist=110.0)
                self._enter_state("WANDER", self.rng.uniform(2.8, 5.4))
                return
            if r < 0.66:
                self.waypoint = self._pick_waypoint(max_dist=460.0, min_dist=170.0)
                self._enter_state("SCURRY", self.rng.uniform(1.5, 2.7))
                return
            if r < 0.84:
                self.trigger_trick(None)
                return
        else:
            if r < 0.35:
                self.trigger_trick(self.rng.choice(["WAVE", "SCAN", "THREAT"]))
                return

        self._enter_state("IDLE", self.rng.uniform(2.8, 5.5))

    def _step_dangle_springs(self, dt: float) -> dict[str, tuple[float, float]]:
        """Advance per-leg 2D spring-damper inertia in spider-local space (360-deg invariant)."""
        inv_s = 1.0 / max(0.22, self.gait.scale)
        # World-space inertial trail opposite to mouse drag + gentle screen-downward gravity droop
        vx_w = -self.drag_vx * inv_s * 0.052
        vy_w = -self.drag_vy * inv_s * 0.052 + 22.0

        # Unrotate world vector into spider-local rest space so legs always trail opposite screen drag
        rad = math.radians(self.heading_deg)
        ca, sa = math.cos(rad), math.sin(rad)
        trail_lx = vx_w * ca + vy_w * sa
        trail_ly = -vx_w * sa + vy_w * ca

        overrides = {}
        for lid, (hx, hy) in self.dangle_home_local.items():
            k, damp, phase, max_d = self.DANGLE_SPRING_SPEC[lid]
            sx, sy, vx, vy = self.dangle_springs[lid]

            is_palp = lid in ("L4", "R4")
            wig_amp = 2.8 if is_palp else 13.5
            t_scale = 0.18 if is_palp else 1.0
            wig_x = math.sin(self.clock * 9.2 + phase) * wig_amp
            wig_y = math.cos(self.clock * 7.6 + phase * 1.3) * (wig_amp * 0.58)

            des_x = max(-max_d, min(max_d, trail_lx * t_scale + wig_x))
            des_y = max(-max_d, min(max_d, trail_ly * t_scale + wig_y))

            ax = k * (des_x - sx) - damp * vx
            ay = k * (des_y - sy) - damp * vy
            vx += ax * dt
            vy += ay * dt
            sx = max(-max_d, min(max_d, sx + vx * dt))
            sy = max(-max_d, min(max_d, sy + vy * dt))

            self.dangle_springs[lid] = [sx, sy, vx, vy]
            overrides[lid] = (hx + sx, hy + sy)
        return overrides

    # -------------------- Per-Frame Update --------------------

    def _update_blink(self, dt: float) -> float:
        if self.state == "SLEEP":
            return 0.78 + 0.05 * math.sin(self.clock * 1.6)

        if self.blink_timer >= 0.0:
            self.blink_timer += dt
            if self.blink_timer >= self.blink_duration:
                self.blink_timer = -1.0
                self.next_blink_in = self.rng.uniform(2.5, 5.8)
                return 0.0
            return math.sin(math.pi * (self.blink_timer / self.blink_duration))

        self.next_blink_in -= dt
        if self.next_blink_in <= 0.0:
            self.blink_timer = 0.0
        return 0.0

    def update(self, dt: float, cursor_pos: tuple[float, float] | None = None) -> dict:
        """
        Advance AI, gait, and procedural animation by dt seconds.
        Returns a frame state dict ready for NeonSpiderRenderer.render_frame().
        """
        dt = min(0.05, max(1e-4, float(dt)))
        self.clock += dt
        self.state_time += dt

        # Defaults for this frame
        extra_offset = [0.0, 0.0]
        local_offset = [0.0, 0.0]
        extra_tilt = 0.0
        target_wag = 0.0
        palp_boost = 0.0
        scan_pulse = 0.0
        glow_strength = 1.0
        hud_rate = 1.0
        stance_spread = 1.0
        step_speed_mult = 1.0
        airborne = False
        target_desk_pos = None
        local_foot_overrides: dict[str, tuple[float, float]] = {}
        foot_overrides: dict[str, tuple[float, float]] = {}

        # State transitions
        if self.state_time >= self.state_duration and self.state not in ("SLEEP", "DRAGGED"):
            self._choose_next_autonomous_state()

        s_ratio = self.gait.scale / 0.42

        # Check cursor proximity for companion follow & curiosity tracking
        cursor_dx, cursor_dy, cursor_dist, cursor_prox = 0.0, 0.0, 99999.0, 0.0
        if cursor_pos is not None:
            cursor_dx = float(cursor_pos[0]) - self.gait.desk_x
            cursor_dy = float(cursor_pos[1]) - self.gait.desk_y
            cursor_dist = math.hypot(cursor_dx, cursor_dy)
            sense_r = 460.0 * s_ratio
            if cursor_dist < sense_r:
                cursor_prox = 1.0 - cursor_dist / sense_r

            # Auto-engage FOLLOW when follow_mouse is enabled and cursor moves away
            if (
                self.follow_mouse
                and not self.sleeping
                and not self.stay_put
                and self.state in ("IDLE", "WANDER", "SCURRY")
                and cursor_dist > 185.0 * s_ratio
            ):
                cgx, cgy = self.clamp_to_work_area(cursor_pos[0], cursor_pos[1])
                if math.hypot(cgx - self.gait.desk_x, cgy - self.gait.desk_y) > 20.0 * s_ratio:
                    self._enter_state("FOLLOW", duration=999999.0)

        t = self.state_time

        if self.state == "DRAGGED":
            airborne = True
            raw_vx = (self.drag_target_desk[0] - self.gait.desk_x) / dt
            raw_vy = (self.drag_target_desk[1] - self.gait.desk_y) / dt
            v_blend = 1.0 - math.exp(-18.0 * dt)
            self.drag_vx += (raw_vx - self.drag_vx) * v_blend
            self.drag_vy += (raw_vy - self.drag_vy) * v_blend
            target_desk_pos = self.drag_target_desk

            local_foot_overrides = self._step_dangle_springs(dt)
            rad_h = math.radians(self.heading_deg)
            lat_drag = self.drag_vx * math.cos(rad_h) + self.drag_vy * math.sin(rad_h)
            extra_tilt = max(-14.0, min(14.0, -self.drag_vx * (0.013 / max(0.5, s_ratio))))
            target_wag = max(-13.0, min(13.0, -lat_drag * (0.016 / max(0.5, s_ratio))))
            palp_boost = 0.65
            glow_strength = 1.18
            hud_rate = 2.0

        elif self.state == "SETTLING":
            if t < 0.15:
                airborne = True
                u = t / 0.15
                self.settle_vel[0] *= math.exp(-8.0 * dt)
                self.settle_vel[1] = self.settle_vel[1] * math.exp(-5.0 * dt) + 420.0 * s_ratio * dt
                nx, ny = self.clamp_to_work_area(
                    self.gait.desk_x + self.settle_vel[0] * dt,
                    self.gait.desk_y + self.settle_vel[1] * dt,
                )
                target_desk_pos = (nx, ny)
                s_ease = u * u * (3.0 - 2.0 * u)
                for lid, (sx0, sy0) in self.settle_start_feet.items():
                    hx, hy = self.gait.rest_foot_local[lid]
                    local_foot_overrides[lid] = (sx0 + (hx - sx0) * s_ease, sy0 + (hy - sy0) * s_ease)
            else:
                if not self.settle_landed:
                    self.settle_landed = True
                    nx, ny = self.clamp_to_work_area(self.gait.desk_x, self.gait.desk_y)
                    self.gait.desk_x, self.gait.desk_y = nx, ny
                    self.gait.reset_feet_to_home(stance_spread=1.0, heading_deg=self.heading_deg)
                td = t - 0.15
                extra_offset[1] = 11.5 * math.exp(-10.5 * td) * math.cos(18.0 * td)

        elif self.state == "FOLLOW":
            stop_r = 140.0 * s_ratio
            clamped_goal = self.clamp_to_work_area(cursor_pos[0], cursor_pos[1]) if cursor_pos is not None else (0.0, 0.0)
            goal_dist = math.hypot(clamped_goal[0] - self.gait.desk_x, clamped_goal[1] - self.gait.desk_y)
            if (
                not self.follow_mouse
                or self.stay_put
                or cursor_pos is None
                or cursor_dist <= stop_r
                or goal_dist <= 8.0 * s_ratio
            ):
                self.cmd_vx = 0.0
                self.cmd_vy = 0.0
                self._enter_state("IDLE", self.rng.uniform(2.0, 4.2))
            else:
                eager = cursor_dist > 380.0 * s_ratio
                max_spd = (255.0 if eager else 135.0) * s_ratio
                step_speed_mult = 1.80 if eager else 1.22
                turn_rate = 340.0 if eager else 235.0
                steer_x, steer_y = self._steer_goal_across_monitors(clamped_goal[0], clamped_goal[1])
                want_h = _vec_to_heading_deg(steer_x - self.gait.desk_x, steer_y - self.gait.desk_y)
                err_deg = self._steer_heading(want_h, max_rate_deg=turn_rate, smooth_k=12.5, dt=dt)

                # Turn toward cursor first, then advance along current head direction
                align = max(0.0, math.cos(math.radians(min(92.0, err_deg)))) ** 1.6
                over = cursor_dist - stop_r
                ramp = min(1.0, max(0.22, over / (55.0 * s_ratio)))
                des_spd = max_spd * ramp * align
                rad_h = math.radians(self.heading_deg)
                fwd_x, fwd_y = -math.sin(rad_h), math.cos(rad_h)
                cur_spd = max(0.0, self.cmd_vx * fwd_x + self.cmd_vy * fwd_y)
                blend = 1.0 - math.exp(-10.5 * dt)
                spd = cur_spd + (des_spd - cur_spd) * blend
                self.cmd_vx = fwd_x * spd
                self.cmd_vy = fwd_y * spd
                palp_boost = 0.42 if eager else 0.28

        elif self.state == "IDLE":
            self.cmd_vx *= math.exp(-10.0 * dt)
            self.cmd_vy *= math.exp(-10.0 * dt)
            local_offset[1] = 2.6 * math.sin(self.clock * 2.3)

            # Curious cursor turn-in-place gaze when mouse approaches; otherwise gentle random glance
            if cursor_prox > 0.08 and cursor_dist > 26.0 * s_ratio:
                want_h = _vec_to_heading_deg(cursor_dx, cursor_dy)
                gaze_rate = (75.0 + 135.0 * cursor_prox)
                self._steer_heading(want_h, max_rate_deg=gaze_rate, smooth_k=7.5, dt=dt)
                self.idle_base_heading_deg = self.heading_deg
                self.idle_glance_deg = 0.0
                palp_boost = 0.55 * cursor_prox
            else:
                self.next_glance_in -= dt
                if self.next_glance_in <= 0.0:
                    self.idle_glance_deg = self.rng.choice([-14.0, -7.5, 0.0, 0.0, 7.5, 14.0])
                    self.next_glance_in = self.rng.uniform(1.8, 3.8)
                want_h = wrap_angle_deg(self.idle_base_heading_deg + self.idle_glance_deg)
                self._steer_heading(want_h, max_rate_deg=95.0, smooth_k=6.0, dt=dt)

            # Occasional curious single true-front-foot (L3 / R3) double-tap from exact planted spot
            if self.tap_timer >= 0.0:
                self.tap_timer += dt
                if self.tap_timer >= 0.52:
                    self.tap_timer = -1.0
                    self.next_tap_in = self.rng.uniform(4.5, 8.5)
                else:
                    tap_a = abs(math.sin(self.tap_timer / 0.52 * math.pi * 2.0))
                    cx_m, cy_m = self.gait.body_center_model
                    px, py = self.gait.legs[self.tap_leg].planted_pos
                    wx = cx_m + (px - self.gait.desk_x) / self.gait.scale
                    wy = cy_m + (py - self.gait.desk_y) / self.gait.scale
                    foot_overrides[self.tap_leg] = (
                        wx + (cx_m - wx) * 0.08 * tap_a,
                        wy + (cy_m - wy) * 0.08 * tap_a - 20.0 * tap_a,
                    )
                    palp_boost = max(palp_boost, 0.35)
            else:
                self.next_tap_in -= dt
                if self.next_tap_in <= 0.0 and math.hypot(self.cmd_vx, self.cmd_vy) < 4.0:
                    self.tap_leg = self.rng.choice(["L3", "R3"])
                    self.tap_timer = 0.0

        elif self.state in ("WANDER", "SCURRY"):
            is_scurry = self.state == "SCURRY"
            max_spd = (260.0 if is_scurry else 98.0) * s_ratio
            step_speed_mult = 1.85 if is_scurry else 1.08
            turn_rate = 340.0 if is_scurry else 215.0

            dx = self.waypoint[0] - self.gait.desk_x
            dy = self.waypoint[1] - self.gait.desk_y
            dist = math.hypot(dx, dy)
            if dist < 16.0 * s_ratio or self.stay_put:
                self._choose_next_autonomous_state()
            else:
                steer_x, steer_y = self._steer_goal_across_monitors(self.waypoint[0], self.waypoint[1])
                want_h = _vec_to_heading_deg(steer_x - self.gait.desk_x, steer_y - self.gait.desk_y)
                err_deg = self._steer_heading(
                    want_h,
                    max_rate_deg=turn_rate,
                    smooth_k=13.0 if is_scurry else 9.0,
                    dt=dt,
                )
                align = max(0.0, math.cos(math.radians(min(92.0, err_deg)))) ** 1.6
                ramp = min(1.0, dist / (48.0 * s_ratio))
                des_spd = max_spd * ramp * align
                rad_h = math.radians(self.heading_deg)
                fwd_x, fwd_y = -math.sin(rad_h), math.cos(rad_h)
                cur_spd = max(0.0, self.cmd_vx * fwd_x + self.cmd_vy * fwd_y)
                blend = 1.0 - math.exp(-9.5 * dt)
                spd = cur_spd + (des_spd - cur_spd) * blend
                self.cmd_vx = fwd_x * spd
                self.cmd_vy = fwd_y * spd
                palp_boost = 0.45 if is_scurry else 0.22

        elif self.state == "WAVE":
            self.cmd_vx = self.cmd_vy = 0.0
            p = min(1.0, t / self.state_duration)
            env = math.sin(math.pi * min(1.0, p / 0.18)) if p < 0.18 else (
                math.sin(math.pi * 0.5 * (1.0 - p) / 0.18) if p > 0.82 else 1.0
            )
            w_osc = math.sin((t - 0.15) * 13.5) * env
            # Wave true front leg (L3 or R3) forward along current heading while wiggling mouth pedipalps
            if self.wave_leg == "R3":
                rx0, ry0 = self.gait.rest_foot_local["R3"]  # (996.5, 769.7)
                local_foot_overrides["R3"] = (
                    rx0 + (-40.0 + 46.0 * w_osc) * env,
                    ry0 + (58.0 - 14.0 * abs(w_osc)) * env,
                )
                target_wag = 8.5 * env
                extra_tilt = -3.5 * env
            else:
                lx0, ly0 = self.gait.rest_foot_local["L3"]  # (583.5, 769.7)
                local_foot_overrides["L3"] = (
                    lx0 + (40.0 + 46.0 * w_osc) * env,
                    ly0 + (58.0 - 14.0 * abs(w_osc)) * env,
                )
                target_wag = -8.5 * env
                extra_tilt = 3.5 * env
            local_offset[1] = 3.5 * env
            palp_boost = 0.72 * env

        elif self.state == "THREAT":
            self.cmd_vx = self.cmd_vy = 0.0
            p = min(1.0, t / self.state_duration)
            env = math.sin(math.pi * min(1.0, p / 0.16)) if p < 0.16 else (
                math.sin(math.pi * 0.5 * (1.0 - p) / 0.20) if p > 0.80 else 1.0
            )
            vib = math.sin(t * 22.0) * 12.5 * env
            l3x, l3y = self.gait.rest_foot_local["L3"]
            r3x, r3y = self.gait.rest_foot_local["R3"]
            l4x, l4y = self.gait.rest_foot_local["L4"]
            r4x, r4y = self.gait.rest_foot_local["R4"]

            # Flare both true front legs (L3/R3) wide forward + open mouth pedipalps (L4/R4) like fangs
            local_foot_overrides["L3"] = (l3x - 36.0 * env - vib, l3y + 42.0 * env)
            local_foot_overrides["R3"] = (r3x + 36.0 * env + vib, r3y + 42.0 * env)
            local_foot_overrides["L4"] = (l4x - 18.0 * env - vib * 0.22, l4y + 2.0 * env)
            local_foot_overrides["R4"] = (r4x + 18.0 * env + vib * 0.22, r4y + 2.0 * env)
            local_offset[1] = -10.0 * env  # rear back slightly along -heading
            glow_strength = 1.0 + 0.35 * env
            scan_pulse = 0.28 * env
            hud_rate = 2.4

        elif self.state == "POUNCE":
            self.cmd_vx = self.cmd_vy = 0.0
            if t < 0.36:
                # Phase 1: Turn to face pounce target while crouching back along -heading
                self._steer_heading(self.pounce_heading_deg, max_rate_deg=460.0, smooth_k=18.0, dt=dt)
                c = math.sin(0.5 * math.pi * (t / 0.36))
                local_offset[1] = -13.0 * c
                palp_boost = 0.65 * c
                scan_pulse = 0.35 * c
                glow_strength = 1.0 + 0.25 * c
            elif t < 0.82:
                # Phase 2: Head-first parabolic airborne leap along pounce_heading_deg
                airborne = True
                self._steer_heading(self.pounce_heading_deg, max_rate_deg=520.0, smooth_k=22.0, dt=dt)
                u = (t - 0.36) / 0.46
                arc = 4.0 * u * (1.0 - u)
                jump_h = 82.0 * self.gait.scale
                nx = self.pounce_start[0] + (self.pounce_target[0] - self.pounce_start[0]) * u
                ny = self.pounce_start[1] + (self.pounce_target[1] - self.pounce_start[1]) * u - jump_h * arc
                target_desk_pos = (nx, ny)

                # Reach true front legs (L3/R3) + mouth pedipalps forward; sweep mid/rear legs sleekly back
                l3x, l3y = self.gait.rest_foot_local["L3"]
                r3x, r3y = self.gait.rest_foot_local["R3"]
                l2x, l2y = self.gait.rest_foot_local["L2"]
                r2x, r2y = self.gait.rest_foot_local["R2"]
                l1x, l1y = self.gait.rest_foot_local["L1"]
                r1x, r1y = self.gait.rest_foot_local["R1"]
                l4x, l4y = self.gait.rest_foot_local["L4"]
                r4x, r4y = self.gait.rest_foot_local["R4"]

                local_foot_overrides["L3"] = (l3x + 16.0 * arc, l3y + 34.0 * arc)
                local_foot_overrides["R3"] = (r3x - 16.0 * arc, r3y + 34.0 * arc)
                local_foot_overrides["L2"] = (l2x + 14.0 * arc, l2y - 24.0 * arc)
                local_foot_overrides["R2"] = (r2x - 14.0 * arc, r2y - 24.0 * arc)
                local_foot_overrides["L1"] = (l1x + 16.0 * arc, l1y - 28.0 * arc)
                local_foot_overrides["R1"] = (r1x - 16.0 * arc, r1y - 28.0 * arc)
                local_foot_overrides["L4"] = (l4x - 8.0 * arc, l4y + 2.5 * arc)
                local_foot_overrides["R4"] = (r4x + 8.0 * arc, r4y + 2.5 * arc)
                glow_strength = 1.25
            else:
                # Phase 3: Touchdown & damped squash bounce
                if not self.pounce_landed:
                    self.pounce_landed = True
                    self.gait.desk_x, self.gait.desk_y = self.pounce_target
                    self.gait.reset_feet_to_home(stance_spread=1.0, heading_deg=self.heading_deg)
                td = t - 0.82
                bounce = math.exp(-9.5 * td) * math.cos(17.0 * td)
                local_offset[1] = 6.5 * bounce
                extra_offset[1] = 7.5 * bounce

        elif self.state == "SCAN":
            self.cmd_vx = self.cmd_vy = 0.0
            p = min(1.0, t / self.state_duration)
            scan_pulse = max(0.0, 1.0 - p)
            want_scan_h = wrap_angle_deg(self.scan_base_heading_deg + 22.0 * math.sin(math.tau * p))
            self._steer_heading(want_scan_h, max_rate_deg=180.0, smooth_k=14.0, dt=dt)
            target_wag = -9.5 * math.sin(math.tau * p)
            local_offset[1] = 2.8 * math.sin(math.pi * p)
            palp_boost = 0.70 * math.sin(math.pi * p)
            hud_rate = 3.0
            glow_strength = 1.0 + 0.30 * math.sin(math.pi * p)

        elif self.state == "SLEEP":
            self.cmd_vx *= math.exp(-8.0 * dt)
            self.cmd_vy *= math.exp(-8.0 * dt)
            stance_spread = 0.88
            breath = math.sin(self.clock * 1.6)
            local_offset[1] = 2.2 * breath
            extra_offset[1] = 7.0
            glow_strength = 0.62 + 0.18 * breath
            hud_rate = 0.28
            target_wag = 0.0

        # Subtle curious body lean toward nearby cursor when awake on desktop
        des_lean_x, des_lean_y = 0.0, 0.0
        if cursor_prox > 0.01 and self.state in ("IDLE", "WANDER", "FOLLOW"):
            des_lean_x = max(-4.0, min(4.0, (cursor_dx / (60.0 * s_ratio)))) * cursor_prox
            des_lean_y = max(-3.5, min(3.5, (cursor_dy / (60.0 * s_ratio)))) * cursor_prox

        lean_blend = 1.0 - math.exp(-9.0 * dt)
        self.lean_offset[0] += (des_lean_x - self.lean_offset[0]) * lean_blend
        self.lean_offset[1] += (des_lean_y - self.lean_offset[1]) * lean_blend
        extra_offset[0] += self.lean_offset[0]
        extra_offset[1] += self.lean_offset[1]

        # Clamp desktop coordinates when walking so spider stays inside work area
        if target_desk_pos is None and (abs(self.cmd_vx) > 0.1 or abs(self.cmd_vy) > 0.1):
            nx, ny = self.clamp_to_work_area(
                self.gait.desk_x + self.cmd_vx * dt,
                self.gait.desk_y + self.cmd_vy * dt,
            )
            target_desk_pos = (nx, ny)

        # Advance 360-deg gait, mouth pedipalps, abdomen lag & IK solver
        self.gait.update(
            dt=dt,
            target_desk_pos=target_desk_pos,
            vel_screen=(self.cmd_vx, self.cmd_vy),
            heading_deg=self.heading_deg,
            airborne=airborne,
            stance_spread=stance_spread,
            step_speed_mult=step_speed_mult,
            palp_boost=palp_boost,
        )
        leg_joints, total_offset, total_heading = self.gait.compute_pose(
            extra_body_offset=tuple(extra_offset),
            local_body_offset=tuple(local_offset),
            extra_body_tilt_deg=extra_tilt,
            local_foot_overrides=local_foot_overrides if local_foot_overrides else None,
            model_foot_overrides=foot_overrides if foot_overrides else None,
        )

        # Smooth extra abdomen wag & advance HUD / blink
        wag_blend = 1.0 - math.exp(-12.0 * dt)
        self.extra_wag_deg += (target_wag - self.extra_wag_deg) * wag_blend
        total_wag = max(-18.0, min(18.0, self.gait.abdomen_wag_deg + self.extra_wag_deg))
        self.hud_phase = (self.hud_phase + dt * hud_rate) % 1000.0
        blink = self._update_blink(dt)

        return {
            "state": self.state,
            "desk_pos": (self.gait.desk_x, self.gait.desk_y),
            "leg_joints_world": leg_joints,
            "body_offset": total_offset,
            "heading_deg": total_heading,
            "abdomen_wag_deg": total_wag,
            "body_tilt_deg": total_heading,
            "head_yaw_deg": total_wag,
            "blink": blink,
            "hud_phase": self.hud_phase,
            "scan_pulse": scan_pulse,
            "glow_strength": glow_strength,
        }
