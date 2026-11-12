import math
from ik_solver import SpiderIKSolver


def wrap_angle_deg(deg: float) -> float:
    """Wrap any angle in degrees into [-180, +180)."""
    return ((float(deg) + 180.0) % 360.0) - 180.0


def shortest_angle_diff_deg(target_deg: float, current_deg: float) -> float:
    """Signed shortest angular difference (target - current) in [-180, +180)."""
    return ((float(target_deg) - float(current_deg) + 180.0) % 360.0) - 180.0


class LegStepState:
    __slots__ = ("planted_pos", "start_pos", "target_pos", "progress", "duration", "lift_px", "stepping")

    def __init__(self, pos: tuple[float, float]):
        self.planted_pos = (float(pos[0]), float(pos[1]))
        self.start_pos = self.planted_pos
        self.target_pos = self.planted_pos
        self.progress = 1.0
        self.duration = 0.16
        self.lift_px = 24.0
        self.stepping = False


class SpiderGaitEngine:
    """
    360-degree directional alternating-tripod gait + mouth pedipalp synthesizer + IK pose engine.

    Anatomy convention (at heading_deg = 0.0, facing downward +Y):
      - WALK_LEGS: L3/R3 (front), L2/R2 (middle), L1/R1 (rear) in tripod groups A=(L3,R2,L1) & B=(R3,L2,R1)
      - PALP_LEGS: L4/R4 (short mouth pedipalps / feelers beside the front visor, riding with the head)
    """

    WALK_LEGS = ("L3", "R3", "L2", "R2", "L1", "R1")
    PALP_LEGS = ("L4", "R4")

    def __init__(
        self,
        rig: dict,
        scale: float = 0.42,
        start_desk_pos=(600.0, 500.0),
        start_heading_deg: float = 0.0,
    ):
        self.rig = rig
        self.ik = SpiderIKSolver(rig)
        self.body_center_model = tuple(rig["sprites"]["body"]["center_world"])  # (790.0, 484.0)

        # Filter rig gait groups into pure 6-leg alternating tripods (excluding L4/R4 mouth pedipalps)
        raw_groups = rig["gait"]["groups"]
        self.walk_groups = {
            grp: [lid for lid in lids if lid not in self.PALP_LEGS]
            for grp, lids in raw_groups.items()
        }
        self.groups = self.walk_groups
        self.leg_group = {lid: grp for grp, lids in self.walk_groups.items() for lid in lids}

        self.home_rel_model = {}
        self.rest_foot_local = {}
        for lid, spec in rig["legs"].items():
            fpos = [j["pos"] for j in spec["joints"] if j["id"] == "foot"][0]
            self.rest_foot_local[lid] = (float(fpos[0]), float(fpos[1]))
            self.home_rel_model[lid] = (
                float(fpos[0]) - self.body_center_model[0],
                float(fpos[1]) - self.body_center_model[1],
            )

        self.scale = scale
        self.desk_x, self.desk_y = float(start_desk_pos[0]), float(start_desk_pos[1])
        self.heading_deg = wrap_angle_deg(start_heading_deg)
        self.ang_vel_deg = 0.0
        self.vel_x, self.vel_y = 0.0, 0.0
        self.last_step_group = "B"
        self.landing_impulse = 0.0

        # Mouth pedipalp & inertial abdomen wag states
        self.palp_clock = 0.0
        self.palp_activity = 0.18
        self.abdomen_wag_deg = 0.0

        self.legs: dict[str, LegStepState] = {}
        self.reset_feet_to_home()

    def set_scale(self, new_scale: float):
        if abs(new_scale - self.scale) < 1e-4:
            return
        ratio = new_scale / self.scale
        self.scale = new_scale
        for lid, st in self.legs.items():
            px = self.desk_x + (st.planted_pos[0] - self.desk_x) * ratio
            py = self.desk_y + (st.planted_pos[1] - self.desk_y) * ratio
            st.planted_pos = (px, py)
            st.target_pos = (px, py)
            st.stepping = False
            st.progress = 1.0

    def home_screen_pos(
        self,
        leg_id: str,
        stance_spread: float = 1.0,
        stance_y_shift: float = 0.0,
        heading_deg: float | None = None,
    ) -> tuple[float, float]:
        """Desktop screen coordinates of a leg's ideal stance foot rotated by heading_deg."""
        h_deg = self.heading_deg if heading_deg is None else float(heading_deg)
        lx = self.home_rel_model[leg_id][0] * stance_spread
        ly = self.home_rel_model[leg_id][1] * stance_spread + stance_y_shift
        if abs(h_deg) > 1e-5:
            rad = math.radians(h_deg)
            ca, sa = math.cos(rad), math.sin(rad)
            rx = lx * ca - ly * sa
            ry = lx * sa + ly * ca
        else:
            rx, ry = lx, ly
        return (self.desk_x + rx * self.scale, self.desk_y + ry * self.scale)

    def reset_feet_to_home(
        self,
        stance_spread: float = 1.0,
        stance_y_shift: float = 0.0,
        heading_deg: float | None = None,
    ):
        if heading_deg is not None:
            self.heading_deg = wrap_angle_deg(heading_deg)
            self.ang_vel_deg = 0.0
        for lid in self.rig["legs"]:
            hpos = self.home_screen_pos(lid, stance_spread, stance_y_shift, heading_deg=self.heading_deg)
            self.legs[lid] = LegStepState(hpos)

    def _trigger_threshold_model(self, moving: bool) -> float:
        return 28.0 if moving else 11.0

    def _compute_palp_local_targets(self) -> dict[str, tuple[float, float]]:
        """
        Synthesize expressive 'feeling / rubbing / tasting the air' motions in rest model space
        for the two short mouth pedipalps (L4 & R4) right in front of the square cephalothorax.
        """
        p = self.palp_clock
        act = self.palp_activity  # 0.12 (sleep/calm) .. 1.0 (active scurrying/curious)

        amp_x = 1.8 + 6.8 * act
        amp_y = 1.4 + 5.2 * act
        # Slight inward tuck during active palping keeps 2-bone elbow comfortably bent (62..77 px reach)
        tuck_y = -3.4 * act

        l4_rest = self.rest_foot_local["L4"]  # (743.0, 605.5)
        r4_rest = self.rest_foot_local["R4"]  # (837.0, 605.5)

        lx = l4_rest[0] + math.sin(p * 1.0) * amp_x + math.sin(p * 2.3 + 0.7) * (amp_x * 0.28)
        ly = l4_rest[1] + tuck_y + math.cos(p * 1.35 + 0.4) * amp_y

        rx = r4_rest[0] - math.sin(p * 1.0 + 0.85) * amp_x - math.sin(p * 2.3 + 2.1) * (amp_x * 0.28)
        ry = r4_rest[1] + tuck_y + math.cos(p * 1.35 + 3.1) * amp_y

        return {"L4": (lx, ly), "R4": (rx, ry)}

    def update(
        self,
        dt: float,
        target_desk_pos: tuple[float, float] | None = None,
        vel_screen: tuple[float, float] = (0.0, 0.0),
        heading_deg: float | None = None,
        airborne: bool = False,
        stance_spread: float = 1.0,
        stance_y_shift: float = 0.0,
        step_speed_mult: float = 1.0,
        palp_boost: float = 0.0,
    ):
        dt = min(0.05, max(1e-4, dt))
        if target_desk_pos is not None:
            self.desk_x, self.desk_y = float(target_desk_pos[0]), float(target_desk_pos[1])
        else:
            self.desk_x += vel_screen[0] * dt
            self.desk_y += vel_screen[1] * dt

        self.vel_x, self.vel_y = float(vel_screen[0]), float(vel_screen[1])

        # Smoothly track 360-degree heading & angular velocity (shortest-path wrap)
        if heading_deg is not None:
            new_h = wrap_angle_deg(heading_deg)
            dh = shortest_angle_diff_deg(new_h, self.heading_deg)
            raw_w = dh / dt
            w_blend = 1.0 - math.exp(-16.0 * dt)
            self.ang_vel_deg += (raw_w - self.ang_vel_deg) * w_blend
            self.heading_deg = new_h
        else:
            self.ang_vel_deg *= math.exp(-16.0 * dt)

        speed = math.hypot(self.vel_x, self.vel_y)
        # Tangential foot speed at stance radius (~280 model px) due to turning in place
        rot_foot_speed = abs(math.radians(self.ang_vel_deg)) * (280.0 * self.scale)
        eff_speed = math.hypot(speed, rot_foot_speed)
        moving = eff_speed > 6.0 * self.scale

        # Advance mouth pedipalp feeler rhythm
        want_palp = 0.85 if airborne else min(
            1.0,
            max(0.08, 0.18 + (eff_speed / max(15.0, 175.0 * self.scale)) * 0.65 + palp_boost),
        )
        self.palp_activity += (want_palp - self.palp_activity) * (1.0 - math.exp(-8.0 * dt))
        self.palp_clock = (self.palp_clock + dt * (2.5 + 5.4 * self.palp_activity)) % 10000.0

        # Decay landing micro-bounce
        self.landing_impulse *= math.exp(-14.0 * dt)

        if airborne:
            for lid in self.WALK_LEGS:
                st = self.legs[lid]
                st.stepping = False
                st.progress = 1.0
            # Inertial abdomen trail during mid-air spin
            want_wag = max(-14.5, min(14.5, -self.ang_vel_deg * 0.055))
            self.abdomen_wag_deg += (want_wag - self.abdomen_wag_deg) * (1.0 - math.exp(-10.0 * dt))
            return

        # 1) Advance active walking leg swings
        for lid in self.WALK_LEGS:
            st = self.legs[lid]
            if st.stepping:
                st.progress += dt / st.duration
                if st.progress >= 1.0:
                    st.progress = 1.0
                    st.stepping = False
                    st.planted_pos = st.target_pos
                    self.landing_impulse = min(4.5, self.landing_impulse + 0.85)
            else:
                # Safety tether against extreme instantaneous teleports so legs never detach
                hx, hy = self.home_screen_pos(lid, stance_spread, stance_y_shift)
                dx, dy = st.planted_pos[0] - hx, st.planted_pos[1] - hy
                max_tether = 96.0 * self.scale
                dist = math.hypot(dx, dy)
                if dist > max_tether:
                    st.planted_pos = (hx + dx / dist * max_tether, hy + dy / dist * max_tether)

        # Update inertial abdomen wag (lags behind angular turns + subtle alternating tripod sway)
        a_lift = sum(math.sin(math.pi * self.legs[l].progress) for l in self.walk_groups["A"] if self.legs[l].stepping)
        b_lift = sum(math.sin(math.pi * self.legs[l].progress) for l in self.walk_groups["B"] if self.legs[l].stepping)
        turn_lag_deg = max(-13.5, min(13.5, -self.ang_vel_deg * 0.065))
        gait_wag_deg = (a_lift - b_lift) * 2.1
        want_wag = max(-15.0, min(15.0, turn_lag_deg + gait_wag_deg))
        self.abdomen_wag_deg += (want_wag - self.abdomen_wag_deg) * (1.0 - math.exp(-12.0 * dt))

        # 2) Check which tripod group wants to step (Alternating Tripod A <-> B)
        active_A = any(self.legs[lid].stepping for lid in self.walk_groups["A"])
        active_B = any(self.legs[lid].stepping for lid in self.walk_groups["B"])
        if active_A or active_B:
            return

        turn_cadence = 0.75 + rot_foot_speed / max(18.0, 140.0 * self.scale)
        eff_step_mult = max(step_speed_mult, min(2.25, turn_cadence)) if moving else step_speed_mult

        order = ["B", "A"] if self.last_step_group == "A" else ["A", "B"]
        dur_base = max(0.078, min(0.20, 0.160 / max(0.5, eff_step_mult)))
        thresh = self._trigger_threshold_model(moving)

        for grp in order:
            lids = self.walk_groups[grp]
            needs_urgent = False
            errs = {}
            for lid in lids:
                hx, hy = self.home_screen_pos(lid, stance_spread, stance_y_shift)
                px, py = self.legs[lid].planted_pos
                err_model = math.hypot(px - hx, py - hy) / self.scale
                errs[lid] = err_model
                if err_model > thresh:
                    needs_urgent = True

            if needs_urgent:
                self.last_step_group = grp
                lead_t = dur_base * 0.55
                pred_heading = wrap_angle_deg(
                    self.heading_deg + max(-32.0, min(32.0, self.ang_vel_deg * lead_t))
                )
                lead_cap = 34.0 * self.scale
                lx = max(-lead_cap, min(lead_cap, self.vel_x * lead_t))
                ly = max(-lead_cap, min(lead_cap, self.vel_y * lead_t))

                for lid in lids:
                    if errs[lid] >= thresh * (0.36 if moving else 0.72):
                        st = self.legs[lid]
                        phx, phy = self.home_screen_pos(
                            lid,
                            stance_spread,
                            stance_y_shift,
                            heading_deg=pred_heading,
                        )
                        st.start_pos = st.planted_pos
                        st.target_pos = (phx + lx, phy + ly)
                        st.progress = 0.0
                        st.duration = dur_base
                        st.lift_px = 25.0 * min(1.35, 0.75 + 0.25 * eff_step_mult)
                        st.stepping = True
                break

    def current_foot_world_positions(
        self,
        body_offset=(0.0, 0.0),
        heading_deg: float | None = None,
        local_overrides: dict[str, tuple[float, float]] | None = None,
        world_overrides: dict[str, tuple[float, float]] | None = None,
    ) -> dict[str, list[float]]:
        """
        Compute world-space foot targets for all 8 limbs:
          - 6 walking legs (L1..R3): desktop-anchored planted positions or 360-clean swing arcs
          - 2 mouth pedipalps (L4, R4): head-carried expressive feeler positions
          - local_overrides: limb targets in spider-local rest coords (auto-rotated by heading_deg)
          - world_overrides: limb targets already in world coords (backward-compatible)
        """
        cx, cy = self.body_center_model
        eff_h = self.heading_deg if heading_deg is None else float(heading_deg)
        palp_locals = self._compute_palp_local_targets()

        out = {}
        for lid in self.rig["legs"]:
            if world_overrides and lid in world_overrides:
                out[lid] = [float(world_overrides[lid][0]), float(world_overrides[lid][1])]
                continue

            if local_overrides and lid in local_overrides:
                out[lid] = self.ik.model_local_to_world(
                    local_overrides[lid],
                    body_offset=body_offset,
                    heading_deg=eff_h,
                )
                continue

            if lid in self.PALP_LEGS:
                out[lid] = self.ik.model_local_to_world(
                    palp_locals[lid],
                    body_offset=body_offset,
                    heading_deg=eff_h,
                )
                continue

            st = self.legs[lid]
            if st.stepping:
                t = st.progress
                s = t * t * (3.0 - 2.0 * t)
                sx = st.start_pos[0] + (st.target_pos[0] - st.start_pos[0]) * s
                sy = st.start_pos[1] + (st.target_pos[1] - st.start_pos[1]) * s
                wx = cx + (sx - self.desk_x) / self.scale
                wy = cy + (sy - self.desk_y) / self.scale

                # Radial outward clearance + screen-upward lift (never cancels at any 360° heading)
                arc = math.sin(math.pi * t)
                rx, ry = wx - (cx + body_offset[0]), wy - (cy + body_offset[1])
                rn = max(1e-3, math.hypot(rx, ry))
                wx += (rx / rn) * (6.0 * arc)
                wy += (ry / rn) * (6.0 * arc) - (0.78 * st.lift_px * arc)
                out[lid] = [wx, wy]
            else:
                sx, sy = st.planted_pos
                out[lid] = [
                    cx + (sx - self.desk_x) / self.scale,
                    cy + (sy - self.desk_y) / self.scale,
                ]
        return out

    def current_foot_model_positions(
        self,
        model_overrides: dict[str, tuple[float, float]] | None = None,
    ) -> dict[str, list[float]]:
        """Backward-compatible alias returning world/model foot positions."""
        return self.current_foot_world_positions(world_overrides=model_overrides)

    def compute_pose(
        self,
        extra_body_offset=(0.0, 0.0),
        local_body_offset=(0.0, 0.0),
        extra_body_tilt_deg: float = 0.0,
        local_foot_overrides: dict[str, tuple[float, float]] | None = None,
        model_foot_overrides: dict[str, tuple[float, float]] | None = None,
    ) -> tuple[dict, tuple[float, float], float]:
        """
        Return (leg_joints_world, total_body_offset_world, total_heading_deg).
          - local_body_offset: (right_px, forward_px) in spider-heading coordinates
          - extra_body_offset: (dx, dy) in screen/world coordinates
        """
        a_lift = sum(math.sin(math.pi * self.legs[l].progress) for l in self.walk_groups["A"] if self.legs[l].stepping)
        b_lift = sum(math.sin(math.pi * self.legs[l].progress) for l in self.walk_groups["B"] if self.legs[l].stepping)

        # Spider-local lateral sway + local body offset rotated by heading_deg
        loc_x = float(local_body_offset[0]) + (a_lift - b_lift) * 1.0
        loc_y = float(local_body_offset[1])
        rad = math.radians(self.heading_deg)
        ca, sa = math.cos(rad), math.sin(rad)
        rot_loc_x = loc_x * ca - loc_y * sa
        rot_loc_y = loc_x * sa + loc_y * ca

        gait_bob_y = self.landing_impulse * 0.75 - (a_lift + b_lift) * 0.50
        total_offset = (
            float(extra_body_offset[0]) + rot_loc_x,
            float(extra_body_offset[1]) + rot_loc_y + gait_bob_y,
        )

        # Lateral velocity bank + subtle tripod rock around current heading_deg
        v_lat = (self.vel_x * ca + self.vel_y * sa) / max(0.2, self.scale)
        bank_deg = max(-4.5, min(4.5, v_lat * 0.010))
        total_heading = wrap_angle_deg(
            self.heading_deg + float(extra_body_tilt_deg) + bank_deg + (a_lift - b_lift) * 0.50
        )

        feet_world = self.current_foot_world_positions(
            body_offset=total_offset,
            heading_deg=total_heading,
            local_overrides=local_foot_overrides,
            world_overrides=model_foot_overrides,
        )
        joints = self.ik.solve_all(feet_world, body_offset=total_offset, heading_deg=total_heading)
        return joints, total_offset, total_heading
