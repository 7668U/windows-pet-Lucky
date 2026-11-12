import math


def _dist(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _solve_2bone(p_root, p_target, l1: float, l2: float, bend_sign: float):
    """Exact 2D 2-link analytic IK with graceful clamping at inner/outer workspace limits."""
    dx = p_target[0] - p_root[0]
    dy = p_target[1] - p_root[1]
    raw_d = math.hypot(dx, dy)
    if raw_d < 1e-5:
        ux, uy = 1.0, 0.0
        raw_d = 1e-5
    else:
        ux, uy = dx / raw_d, dy / raw_d

    min_d = abs(l1 - l2) + 1.5
    max_d = (l1 + l2) * 0.998
    d = max(min_d, min(max_d, raw_d))

    # Normal vector (+90 deg in screen coords)
    nx, ny = -uy, ux
    a = (l1 * l1 - l2 * l2 + d * d) / (2.0 * d)
    h = math.sqrt(max(0.0, l1 * l1 - a * a))

    jx = p_root[0] + ux * a + nx * (bend_sign * h)
    jy = p_root[1] + uy * a + ny * (bend_sign * h)

    # Recompute exact end-effector at distance l2 from joint so bone lengths never drift
    edx, edy = p_target[0] - jx, p_target[1] - jy
    ed = math.hypot(edx, edy)
    if ed < 1e-5:
        fx, fy = jx + ux * l2, jy + uy * l2
    else:
        # If target was within reach, p_target is already at distance l2 from (jx, jy)
        if min_d <= raw_d <= max_d:
            fx, fy = p_target[0], p_target[1]
        else:
            fx, fy = jx + (edx / ed) * l2, jy + (edy / ed) * l2

    return [jx, jy], [fx, fy]


def _calib_sign(p0, pj, p1) -> float:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = max(1e-5, math.hypot(dx, dy))
    nx, ny = -dy / d, dx / d
    cross = (pj[0] - p0[0]) * nx + (pj[1] - p0[1]) * ny
    return 1.0 if cross >= 0.0 else -1.0


class SpiderIKSolver:
    """
    Multi-joint analytic IK solver calibrated to rig.json for zero-error rest pose,
    rigid PCB segments, and exact 360-degree rotation invariance around cephalothorax center (790, 484).
    """

    def __init__(self, rig: dict):
        self.rig = rig
        self.body_center = tuple(rig["sprites"]["body"]["center_world"])  # (790.0, 484.0)
        self.leg_cal = {}

        for leg_id, spec in rig["legs"].items():
            jmap = {j["id"]: list(j["pos"]) for j in spec["joints"]}
            mode = spec["ik_mode"]
            root = jmap["root"]
            foot = jmap["foot"]

            entry = {
                "mode": mode,
                "rest_joints": jmap,
                "rest_root": root,
                "rest_foot": foot,
                "rest_chord_angle": math.atan2(foot[1] - root[1], foot[0] - root[0]),
            }

            if mode == "2link":
                j1 = jmap["j1"]
                entry["l0"] = _dist(root, j1)
                entry["l1"] = _dist(j1, foot)
                entry["sign1"] = _calib_sign(root, j1, foot)

            elif mode == "3link":
                j1, j2 = jmap["j1"], jmap["j2"]
                l0 = _dist(root, j1)
                l1 = _dist(j1, j2)
                l2 = _dist(j2, foot)
                a_root_j1 = math.atan2(j1[1] - root[1], j1[0] - root[0])
                # Signed angle of (root -> j1) relative to (root -> foot)
                rel = math.atan2(
                    math.sin(a_root_j1 - entry["rest_chord_angle"]),
                    math.cos(a_root_j1 - entry["rest_chord_angle"]),
                )
                entry.update({
                    "l0": l0,
                    "l1": l1,
                    "l2": l2,
                    "alpha_rest": rel,
                    "alpha_sign": 1.0 if rel >= 0.0 else -1.0,
                    "sign_knee": _calib_sign(j1, j2, foot),
                })

            elif mode == "coxa_2link_dogleg":
                j1, j2, j3 = jmap["j1"], jmap["j2"], jmap["j3"]
                entry.update({
                    "l_coxa": _dist(root, j1),
                    "coxa_rest_angle": math.atan2(j1[1] - root[1], j1[0] - root[0]),
                    "l_femur": _dist(j1, j2),
                    "l_virt": _dist(j2, foot),
                    "l_tibia": _dist(j2, j3),
                    "l_tarsus": _dist(j3, foot),
                    "sign_knee": _calib_sign(j1, j2, foot),
                    "sign_ankle": _calib_sign(j2, j3, foot),
                })

            self.leg_cal[leg_id] = entry

    def model_local_to_world(
        self,
        local_pt,
        body_offset=(0.0, 0.0),
        heading_deg: float = 0.0,
    ) -> list[float]:
        """Transform a point from unrotated rest model space (facing +Y) to rotated world space."""
        cx, cy = self.body_center
        dx = float(local_pt[0]) - cx
        dy = float(local_pt[1]) - cy
        if abs(heading_deg) > 1e-5:
            rad = math.radians(heading_deg)
            ca, sa = math.cos(rad), math.sin(rad)
            dx, dy = dx * ca - dy * sa, dx * sa + dy * ca
        return [cx + dx + body_offset[0], cy + dy + body_offset[1]]

    def world_to_model_local(
        self,
        world_pt,
        body_offset=(0.0, 0.0),
        heading_deg: float = 0.0,
    ) -> list[float]:
        """Inverse transform from rotated world space back to unrotated rest model space."""
        cx, cy = self.body_center
        dx = float(world_pt[0]) - (cx + body_offset[0])
        dy = float(world_pt[1]) - (cy + body_offset[1])
        if abs(heading_deg) > 1e-5:
            rad = math.radians(heading_deg)
            ca, sa = math.cos(rad), math.sin(rad)
            dx, dy = dx * ca + dy * sa, -dx * sa + dy * ca
        return [cx + dx, cy + dy]

    def get_root_world(
        self,
        leg_id: str,
        body_offset=(0.0, 0.0),
        heading_deg: float = 0.0,
        body_tilt_deg: float | None = None,
    ) -> list[float]:
        eff_deg = heading_deg if body_tilt_deg is None else body_tilt_deg
        return self.model_local_to_world(self.leg_cal[leg_id]["rest_root"], body_offset, eff_deg)

    def _solve_leg_rest_local(self, leg_id: str, local_target: list[float]) -> dict[str, list[float]]:
        """Solve single-leg IK strictly in unrotated rest model space (zero wrap/flip artifacts)."""
        cal = self.leg_cal[leg_id]
        mode = cal["mode"]
        root = [cal["rest_root"][0], cal["rest_root"][1]]
        target = [float(local_target[0]), float(local_target[1])]

        if mode == "2link":
            j1, f_out = _solve_2bone(root, target, cal["l0"], cal["l1"], cal["sign1"])
            return {"root": root, "j1": j1, "foot": f_out}

        if mode == "3link":
            l0, l1, l2 = cal["l0"], cal["l1"], cal["l2"]
            dx, dy = target[0] - root[0], target[1] - root[1]
            d = max(1e-4, math.hypot(dx, dy))
            chord_ang = math.atan2(dy, dx)

            # Feasible distance from j1 to target for (l1, l2)
            d23_min = abs(l1 - l2) + 2.5
            d23_max = (l1 + l2) * 0.994

            # Law of cosines on (root, j1, target): cos(alpha) = (l0^2 + d^2 - d23^2) / (2*l0*d)
            denom = 2.0 * l0 * d
            cos_lo = max(-0.995, min(0.995, (l0 * l0 + d * d - d23_max * d23_max) / denom))
            cos_hi = max(-0.995, min(0.995, (l0 * l0 + d * d - d23_min * d23_min) / denom))
            if cos_lo > cos_hi:
                cos_lo, cos_hi = cos_hi, cos_lo

            want_mag = abs(cal["alpha_rest"])
            c_want = math.cos(want_mag)
            c_clamped = max(cos_lo, min(cos_hi, c_want))
            alpha = cal["alpha_sign"] * math.acos(max(-1.0, min(1.0, c_clamped)))

            ang0 = chord_ang + alpha
            j1 = [root[0] + l0 * math.cos(ang0), root[1] + l0 * math.sin(ang0)]
            j2, f_out = _solve_2bone(j1, target, l1, l2, cal["sign_knee"])
            return {"root": root, "j1": j1, "j2": j2, "foot": f_out}

        if mode == "coxa_2link_dogleg":
            chord_ang = math.atan2(target[1] - root[1], target[0] - root[0])
            swing = math.atan2(
                math.sin(chord_ang - cal["rest_chord_angle"]),
                math.cos(chord_ang - cal["rest_chord_angle"]),
            )
            coxa_ang = cal["coxa_rest_angle"] + swing * 0.25
            j1 = [root[0] + cal["l_coxa"] * math.cos(coxa_ang), root[1] + cal["l_coxa"] * math.sin(coxa_ang)]
            j2, f_virt = _solve_2bone(j1, target, cal["l_femur"], cal["l_virt"], cal["sign_knee"])
            j3, f_out = _solve_2bone(j2, f_virt, cal["l_tibia"], cal["l_tarsus"], cal["sign_ankle"])
            return {"root": root, "j1": j1, "j2": j2, "j3": j3, "foot": f_out}

        raise ValueError(f"Unknown IK mode: {mode}")

    def solve_leg(
        self,
        leg_id: str,
        foot_world,
        body_offset=(0.0, 0.0),
        heading_deg: float = 0.0,
        body_tilt_deg: float | None = None,
    ) -> dict[str, list[float]]:
        eff_deg = heading_deg if body_tilt_deg is None else body_tilt_deg
        local_target = self.world_to_model_local(foot_world, body_offset=body_offset, heading_deg=eff_deg)
        local_joints = self._solve_leg_rest_local(leg_id, local_target)
        return {
            jid: self.model_local_to_world(jpos, body_offset=body_offset, heading_deg=eff_deg)
            for jid, jpos in local_joints.items()
        }

    def solve_all(
        self,
        feet_world: dict[str, list[float]],
        body_offset=(0.0, 0.0),
        heading_deg: float = 0.0,
        body_tilt_deg: float | None = None,
    ) -> dict[str, dict[str, list[float]]]:
        return {
            lid: self.solve_leg(
                lid,
                feet_world[lid],
                body_offset=body_offset,
                heading_deg=heading_deg,
                body_tilt_deg=body_tilt_deg,
            )
            for lid in self.rig["legs"]
        }
