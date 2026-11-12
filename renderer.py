import json
import math
import os
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter


class NeonSpiderRenderer:
    """
    High-FPS 32-bit RGBA / premultiplied-BGRA neon renderer for the top-down cyberpunk spider pet.

    Anatomy convention (top-down view, rest pose facing +Y downward / 6 o'clock):
      - Cephalothorax (true square Head, assets/body.png): center at world (790.0, 484.0),
        carries all 6 walking legs (L3/R3 front, L2/R2 mid, L1/R1 rear) + 2 mouth pedipalps (L4/R4).
      - Abdomen (hexagonal HUD carapace, assets/head.png): attached behind cephalothorax at
        waist pivot world (790.0, 386.0), sways with abdomen_wag_deg relative to heading_deg.
    """

    def __init__(self, project_dir: str, scale: float = 0.42):
        self.project_dir = project_dir
        with open(os.path.join(project_dir, "assets", "rig.json"), "r", encoding="utf-8") as f:
            self.rig = json.load(f)

        # Raw RGBA sprites (abdomen = hexagonal upper sprite, ceph = square lower head sprite)
        self.abdomen_raw = Image.open(os.path.join(project_dir, "assets", "head.png")).convert("RGBA")
        self.ceph_raw = Image.open(os.path.join(project_dir, "assets", "body.png")).convert("RGBA")

        # Symmetric 920x920 world box centered on cephalothorax (790, 484) -> 360-deg rotation never clips
        cx_w, cy_w = self.rig["sprites"]["body"]["center_world"]  # (790.0, 484.0)
        half_span = 460.0
        self.world_origin = (cx_w - half_span, cy_w - half_span)  # (330.0, 24.0)
        self.base_size = (int(half_span * 2), int(half_span * 2))  # (920, 920)

        self.scale = 1.0
        self.canvas_size = (386, 386)
        self._ceph_centered = None
        self._ceph_rad = 0
        self._ceph_paste_off = (0, 0)
        self._abd_centered = None
        self._abd_rad = 0
        self._abd_paste_off = (0, 0)
        self.set_scale(scale)

    def set_scale(self, scale: float):
        scale = max(0.24, min(0.85, float(scale)))
        if abs(scale - self.scale) < 1e-4 and self._ceph_centered is not None:
            return
        self.scale = scale
        side = max(64, int(round(self.base_size[0] * scale)))
        self.canvas_size = (side, side)

        # 1) Scale & center square cephalothorax (true head) on its rotation pivot (76, 104)
        cw = max(16, int(round(self.ceph_raw.width * scale)))
        ch = max(16, int(round(self.ceph_raw.height * scale)))
        ceph_s = self.ceph_raw.resize((cw, ch), Image.Resampling.LANCZOS)
        cpx, cpy = [v * scale for v in self.rig["sprites"]["body"]["center_local"]]
        crad = int(math.ceil(math.hypot(max(cpx, cw - cpx), max(cpy, ch - cpy)))) + 2
        self._ceph_rad = crad
        self._ceph_centered = Image.new("RGBA", (crad * 2, crad * 2), (0, 0, 0, 0))
        cox, coy = int(round(crad - cpx)), int(round(crad - cpy))
        self._ceph_paste_off = (cox, coy)
        self._ceph_centered.paste(ceph_s, (cox, coy))

        # 2) Scale & center hexagonal abdomen on its waist pivot (82, 166) so 360-deg rotation never clips
        aw = max(16, int(round(self.abdomen_raw.width * scale)))
        ah = max(16, int(round(self.abdomen_raw.height * scale)))
        abd_s = self.abdomen_raw.resize((aw, ah), Image.Resampling.LANCZOS)
        apx, apy = [v * scale for v in self.rig["sprites"]["head"]["pivot_local"]]
        arad = int(math.ceil(math.hypot(max(apx, aw - apx), max(apy, ah - apy)))) + 2
        self._abd_rad = arad
        self._abd_centered = Image.new("RGBA", (arad * 2, arad * 2), (0, 0, 0, 0))
        aox, aoy = int(round(arad - apx)), int(round(arad - apy))
        self._abd_paste_off = (aox, aoy)
        self._abd_centered.paste(abd_s, (aox, aoy))

    def world_to_canvas(self, pt):
        ox, oy = self.world_origin
        return ((pt[0] - ox) * self.scale, (pt[1] - oy) * self.scale)

    def canvas_to_world(self, pt):
        ox, oy = self.world_origin
        return (pt[0] / self.scale + ox, pt[1] / self.scale + oy)

    @staticmethod
    def _draw_grad_line(draw: ImageDraw.ImageDraw, p0, p1, width_px: float, c0, c1, steps: int = 8):
        w = max(1, int(round(width_px)))
        x0, y0 = p0
        x1, y1 = p1
        if steps <= 1 or c0 == c1:
            draw.line([p0, p1], fill=tuple(c0), width=w)
            return
        for i in range(steps):
            t0 = i / steps
            t1 = (i + 1) / steps
            tm = 0.5 * (t0 + t1)
            col = tuple(int(c0[k] + (c1[k] - c0[k]) * tm) for k in range(4))
            draw.line(
                [(x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)],
                fill=col,
                width=w,
            )

    def _make_ceph_frame(self, blink: float, scan_pulse: float) -> Image.Image:
        """Animate front visor blink & scan boost on the square cephalothorax (true head)."""
        if blink <= 0.05 and scan_pulse <= 0.05:
            return self._ceph_centered
        ceph = self._ceph_centered.copy()
        s = self.scale
        cox, coy = self._ceph_paste_off
        draw = ImageDraw.Draw(ceph)

        # Front glowing visor strip across the mouth-end of the square head (local x=28..124, y=138..147)
        vx0, vy0 = cox + 28.0 * s, coy + 138.0 * s
        vx1, vy1 = cox + 124.0 * s, coy + 147.0 * s
        if blink > 0.05:
            lid_a = int(min(235, 245 * blink))
            overlay = Image.new("RGBA", ceph.size, (0, 0, 0, 0))
            odraw = ImageDraw.Draw(overlay)
            odraw.rectangle([vx0, vy0, vx1, vy1], fill=(22, 12, 46, lid_a))
            overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), ceph.getchannel("A")))
            ceph = Image.alpha_composite(ceph, overlay)
        elif scan_pulse > 0.05:
            boost_a = int(115 * scan_pulse)
            draw.rectangle([vx0 + 4 * s, vy0 + 1 * s, vx1 - 4 * s, vy1 - 1 * s], fill=(190, 255, 255, boost_a))
        return ceph

    def _make_abdomen_frame(self, blink: float, hud_phase: float, scan_pulse: float) -> Image.Image:
        """Animate hexagonal HUD code-screen shimmer & indicator bars on the abdomen."""
        abd = self._abd_centered.copy()
        s = self.scale
        aox, aoy = self._abd_paste_off

        rx0, ry0, rx1, ry1 = [v * s for v in self.rig["sprites"]["head"]["hud_code_rect_local"]]
        rx0, rx1 = rx0 + aox, rx1 + aox
        ry0, ry1 = ry0 + aoy, ry1 + aoy
        if ry1 > ry0 + 6:
            scan_y = ry0 + ((hud_phase * 0.65) % 1.0) * (ry1 - ry0 - 2)
            alpha_bar = int(38 + 45 * scan_pulse + 18 * math.sin(hud_phase * 4.0))
            shimmer = Image.new("RGBA", abd.size, (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shimmer)
            sdraw.rectangle([rx0 + 4 * s, scan_y, rx1 - 4 * s, scan_y + max(1.5, 2.5 * s)], fill=(40, 245, 255, alpha_bar))
            shimmer.putalpha(ImageChops.multiply(shimmer.getchannel("A"), abd.getchannel("A")))
            abd = Image.alpha_composite(abd, shimmer)

        # Dim the two cyan HUD status bars gently when sleeping (blink > 0.45) or boost on radar scan
        hx0, hy0, _, _ = self.rig["sprites"]["head"]["crop_box"]
        bars = self.rig["sprites"]["head"]["eyes"]
        draw = ImageDraw.Draw(abd)
        if blink > 0.45:
            lid_a = int(min(220, 230 * blink))
            for ek in ("main_L", "main_R"):
                bx0, by0, bx1, by1 = bars[ek]["bbox_world"]
                draw.rectangle(
                    [aox + (bx0 - hx0 - 1) * s, aoy + (by0 - hy0 - 1) * s, aox + (bx1 - hx0 + 1) * s, aoy + (by1 - hy0 + 1) * s],
                    fill=(24, 14, 48, lid_a),
                )
        elif scan_pulse > 0.05:
            boost_a = int(120 * scan_pulse)
            for ek in ("main_L", "main_R"):
                bx0, by0, bx1, by1 = bars[ek]["bbox_world"]
                draw.rectangle(
                    [aox + (bx0 - hx0) * s, aoy + (by0 - hy0) * s, aox + (bx1 - hx0) * s, aoy + (by1 - hy0) * s],
                    fill=(210, 255, 255, boost_a),
                )
        return abd

    def render_frame(
        self,
        leg_joints_world: dict | None = None,
        body_offset=(0.0, 0.0),
        heading_deg: float | None = None,
        abdomen_wag_deg: float | None = None,
        body_tilt_deg: float = 0.0,
        head_yaw_deg: float = 0.0,
        blink: float = 0.0,
        hud_phase: float = 0.0,
        scan_pulse: float = 0.0,
        glow_strength: float = 1.0,
    ) -> Image.Image:
        """
        Render a complete 32-bit straight-alpha RGBA frame for any 0..360 deg heading.
        heading_deg=0 faces +Y (downward, rest pose); -90 faces +X (right); +90 faces -X (left); 180 faces -Y (up).
        """
        eff_heading = float(body_tilt_deg if heading_deg is None else heading_deg)
        eff_wag = float(head_yaw_deg if abdomen_wag_deg is None else abdomen_wag_deg)

        cw, ch = self.canvas_size
        s = self.scale
        ss = 2 if s < 0.55 else 1
        lw, lh = cw * ss, ch * ss

        leg_hi = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(leg_hi)

        def to_leg_px(wpt):
            cx, cy = self.world_to_canvas(wpt)
            return (cx * ss, cy * ss)

        # 1) Render 6 articulated neon PCB walking legs + 2 front mouth pedipalps (L4/R4)
        for leg_id, spec in self.rig["legs"].items():
            if leg_joints_world and leg_id in leg_joints_world:
                jmap = leg_joints_world[leg_id]
            else:
                jmap = {j["id"]: j["pos"] for j in spec["joints"]}

            for seg in spec["segments"]:
                p0 = to_leg_px(jmap[seg["from"]])
                p1 = to_leg_px(jmap[seg["to"]])
                self._draw_grad_line(draw, p0, p1, seg["width"] * s * ss, seg["start_rgba"], seg["end_rgba"], steps=6)
                self._draw_grad_line(draw, p0, p1, seg["core_width"] * s * ss, seg["core_rgba"], seg["core_rgba"], steps=1)

                if "pcb_parallel" in seg:
                    pp = seg["pcb_parallel"]
                    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                    L = math.hypot(dx, dy)
                    if L > 2.0:
                        nx, ny = -dy / L, dx / L
                        off = pp["offset_px"] * s * ss
                        t0, t1 = pp["t_range"]
                        q0 = (p0[0] + dx * t0 + nx * off, p0[1] + dy * t0 + ny * off)
                        q1 = (p0[0] + dx * t1 + nx * off, p0[1] + dy * t1 + ny * off)
                        pw = max(1, int(round(pp["width"] * s * ss)))
                        col = tuple(pp["rgba"])
                        draw.line([q0, q1], fill=col, width=pw)
                        if pp.get("dogleg"):
                            d0 = (p0[0] + dx * max(0.02, t0 - 0.05), p0[1] + dy * max(0.02, t0 - 0.05))
                            d1 = (p0[0] + dx * min(0.98, t1 + 0.05), p0[1] + dy * min(0.98, t1 + 0.05))
                            draw.line([d0, q0], fill=col, width=pw)
                            draw.line([q1, d1], fill=col, width=pw)

            for j in spec["joints"]:
                st = j["style"]
                if st == "root_socket":
                    continue
                cx, cy = to_leg_px(jmap[j["id"]])
                jw = max(3.0, j["size"][0] * s * ss)
                jh = max(3.0, j["size"][1] * s * ss)
                bx0, by0 = int(round(cx - jw * 0.5)), int(round(cy - jh * 0.5))
                bx1, by1 = bx0 + int(round(jw)), by0 + int(round(jh))
                if st in ("square_box", "ankle_cap"):
                    bpx = max(1, int(round(j["border_px"] * s * ss)))
                    draw.rectangle([bx0, by0, bx1, by1], fill=tuple(j["outer_rgba"]))
                    if bx1 - bx0 > bpx * 2 and by1 - by0 > bpx * 2:
                        draw.rectangle([bx0 + bpx, by0 + bpx, bx1 - bpx, by1 - bpx], fill=tuple(j["inner_rgba"]))
                elif st == "foot_pad":
                    cap_h = max(1, int(round(3.0 * s * ss)))
                    draw.rectangle([bx0, by0, bx1, by1], fill=tuple(j["pad_rgba"]))
                    draw.rectangle([bx0, by0, bx1, min(by1, by0 + cap_h)], fill=tuple(j["cap_rgba"]))

        leg_base = leg_hi.resize((cw, ch), Image.Resampling.BILINEAR) if ss > 1 else leg_hi

        # 2) Fast multi-scale SIMD neon bloom on half-res buffer (zero dark halo via premultiplied blur)
        frame = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        if glow_strength > 0.02:
            gw, gh = max(16, cw // 2), max(16, ch // 2)
            small = leg_base.resize((gw, gh), Image.Resampling.BILINEAR)
            arr = np.array(small, dtype=np.float32)
            a_norm = arr[:, :, 3:4] / 255.0
            pre = np.concatenate([arr[:, :, :3] * a_norm, arr[:, :, 3:4]], axis=2)
            pre_img = Image.fromarray(np.clip(pre, 0, 255).astype(np.uint8), "RGBA")
            b1 = np.array(pre_img.filter(ImageFilter.GaussianBlur(radius=max(1.0, 1.3 * s * 2))), dtype=np.float32)
            b2 = np.array(pre_img.filter(ImageFilter.GaussianBlur(radius=max(2.2, 3.2 * s * 2))), dtype=np.float32)
            g_pre = (b1 * 0.62 + b2 * 0.48) * glow_strength
            ga = np.clip(g_pre[:, :, 3:4], 0.0, 255.0)
            safe_a = np.where(ga > 0.5, ga / 255.0, 1.0)
            grgb = np.clip(g_pre[:, :, :3] / safe_a, 0.0, 255.0)
            glow_small = Image.fromarray(np.concatenate([grgb, ga], axis=2).astype(np.uint8), "RGBA")
            frame = glow_small.resize((cw, ch), Image.Resampling.BILINEAR)

        # Optional isotropic cyber scan pulse wave ring
        if scan_pulse > 0.01:
            ring_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            rdraw = ImageDraw.Draw(ring_layer)
            bcx, bcy = self.world_to_canvas((790.0 + body_offset[0], 484.0 + body_offset[1]))
            rad = (65.0 + 310.0 * (1.0 - scan_pulse)) * s
            ra = int(155 * scan_pulse)
            rdraw.ellipse([bcx - rad, bcy - rad, bcx + rad, bcy + rad], outline=(35, 245, 255, ra), width=max(1, int(2.5 * s)))
            frame = Image.alpha_composite(frame, ring_layer)

        frame = Image.alpha_composite(frame, leg_base)

        # 3) Composite square Cephalothorax (true Head) rotated by eff_heading around (790, 484)
        bdx, bdy = body_offset
        ceph_spr = self._make_ceph_frame(blink=blink, scan_pulse=scan_pulse)
        if abs(eff_heading) > 0.05:
            ceph_spr = ceph_spr.rotate(-eff_heading, resample=Image.Resampling.BICUBIC, expand=False)
        c_cx, c_cy = self.world_to_canvas((790.0 + bdx, 484.0 + bdy))
        frame.alpha_composite(ceph_spr, (int(round(c_cx - self._ceph_rad)), int(round(c_cy - self._ceph_rad))))

        # 4) Composite hexagonal Abdomen attached to rotated waist pivot (rest offset (0, -98) from (790, 484))
        rad_h = math.radians(eff_heading)
        waist_world = (
            790.0 + bdx + 98.0 * math.sin(rad_h),
            484.0 + bdy - 98.0 * math.cos(rad_h),
        )
        total_abd_deg = eff_heading + eff_wag
        abd_spr = self._make_abdomen_frame(blink=blink, hud_phase=hud_phase, scan_pulse=scan_pulse)
        if abs(total_abd_deg) > 0.05:
            abd_spr = abd_spr.rotate(-total_abd_deg, resample=Image.Resampling.BICUBIC, expand=False)
        w_cx, w_cy = self.world_to_canvas(waist_world)
        frame.alpha_composite(abd_spr, (int(round(w_cx - self._abd_rad)), int(round(w_cy - self._abd_rad))))

        return frame

    @staticmethod
    def to_premultiplied_bgra(rgba_img: Image.Image) -> bytes:
        """Convert straight RGBA PIL Image to Win32 UpdateLayeredWindow premultiplied BGRA bytes."""
        arr = np.asarray(rgba_img, dtype=np.uint16)
        a = arr[:, :, 3:4]
        rgb_pre = (arr[:, :, :3] * a + 127) // 255
        bgra = np.empty(arr.shape, dtype=np.uint8)
        bgra[:, :, 0] = rgb_pre[:, :, 2]  # B
        bgra[:, :, 1] = rgb_pre[:, :, 1]  # G
        bgra[:, :, 2] = rgb_pre[:, :, 0]  # R
        bgra[:, :, 3] = a[:, :, 0]        # A
        return bgra.tobytes()
