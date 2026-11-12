import ctypes
from ctypes import wintypes
import time

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# 64-bit safe Win32 pointer/integer types
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080

WM_DESTROY = 0x0002
WM_KEYDOWN = 0x0100
WM_COMMAND = 0x0111
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
WM_NCHITTEST = 0x0084

VK_ESCAPE = 0x1B
HTTRANSPARENT = -1
HTCLIENT = 1
CS_DBLCLKS = 0x0008
IDC_HAND = 32649
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0
DIB_RGB_COLORS = 0
SPI_GETWORKAREA = 0x0030

MF_STRING = 0x0000
MF_CHECKED = 0x0008
MF_SEPARATOR = 0x0800
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), LPARAM
)


# Explicit 64-bit signatures
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
    wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.COLORREF,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, WPARAM, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.CheckMenuRadioItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.CheckMenuRadioItem.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID
]
user32.TrackPopupMenu.restype = wintypes.BOOL
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCapture.argtypes = [wintypes.HWND]
user32.SetCapture.restype = wintypes.HWND
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), MONITORENUMPROC, LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def enable_dpi_awareness():
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def _signed_word(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


class LayeredPetWindow:
    """Native Win32 per-pixel 32-bit alpha topmost desktop pet window."""

    _class_registered = False
    _CLASS_NAME = "NeonSpiderLayeredPetWnd"

    def __init__(self, title: str = "Neon Spider Pet"):
        enable_dpi_awareness()
        self.hinst = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wnd_proc)

        if not LayeredPetWindow._class_registered:
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = CS_DBLCLKS
            wc.lpfnWndProc = self._wndproc_ref
            wc.hInstance = self.hinst
            wc.hCursor = user32.LoadCursorW(None, ctypes.cast(IDC_HAND, wintypes.LPCWSTR))
            wc.lpszClassName = self._CLASS_NAME
            user32.RegisterClassExW(ctypes.byref(wc))
            LayeredPetWindow._class_registered = True

        self.win_x = 200
        self.win_y = 200
        self.width = 0
        self.height = 0
        self._alpha_map = None
        self.running = True
        self._dragging = False
        self._last_drag_pt = (0, 0)
        self._last_drag_t = 0.0
        self._drag_vel = (0.0, 0.0)

        # Event hooks
        self.on_drag_start = None
        self.on_drag_move = None
        self.on_drag_end = None
        self.on_double_click = None
        self.on_wheel = None
        self.build_menu_items = None
        self.on_menu_command = None

        self._mem_dc = gdi32.CreateCompatibleDC(None)
        self._dib = None
        self._old_bmp = None
        self._bits_ptr = ctypes.c_void_p()

        ex_style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
        self.hwnd = user32.CreateWindowExW(
            ex_style, self._CLASS_NAME, title, WS_POPUP | WS_VISIBLE,
            self.win_x, self.win_y, 10, 10, None, None, self.hinst, None
        )
        if not self.hwnd:
            raise RuntimeError("Failed to create Win32 layered window")

    def _ensure_dib(self, w: int, h: int):
        if w == self.width and h == self.height and self._dib:
            return
        if self._dib:
            gdi32.SelectObject(self._mem_dc, self._old_bmp)
            gdi32.DeleteObject(self._dib)
            self._dib = None

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # Top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(self._mem_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not hbmp:
            raise RuntimeError("CreateDIBSection failed")
        self._old_bmp = gdi32.SelectObject(self._mem_dc, hbmp)
        self._dib = hbmp
        self._bits_ptr = bits
        self.width, self.height = w, h

    def present(self, bgra_premult: bytes, alpha_channel, x: int, y: int, width: int, height: int):
        """Blit premultiplied 32-bit BGRA frame via UpdateLayeredWindow."""
        if not self.hwnd or not self.running:
            return
        self._ensure_dib(width, height)
        self.win_x = int(round(x))
        self.win_y = int(round(y))
        self._alpha_map = alpha_channel

        ctypes.memmove(self._bits_ptr, bgra_premult, width * height * 4)

        dst_pt = wintypes.POINT(self.win_x, self.win_y)
        wnd_sz = wintypes.SIZE(width, height)
        src_pt = wintypes.POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        screen_dc = user32.GetDC(None)
        try:
            user32.UpdateLayeredWindow(
                self.hwnd, screen_dc, ctypes.byref(dst_pt), ctypes.byref(wnd_sz),
                self._mem_dc, ctypes.byref(src_pt), 0, ctypes.byref(blend), ULW_ALPHA
            )
        finally:
            user32.ReleaseDC(None, screen_dc)

    @staticmethod
    def get_work_area() -> tuple[int, int, int, int]:
        enable_dpi_awareness()
        rc = wintypes.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rc), 0)
        return (rc.left, rc.top, rc.right, rc.bottom)

    @staticmethod
    def get_monitor_work_areas() -> list[tuple[int, int, int, int]]:
        """Return work-area rects (left, top, right, bottom) for all connected monitors (primary first)."""
        enable_dpi_awareness()
        primaries: list[tuple[int, int, int, int]] = []
        others: list[tuple[int, int, int, int]] = []

        def _enum_cb(hmon, hdc, lprc, lparam):
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                w = mi.rcWork
                rect = (int(w.left), int(w.top), int(w.right), int(w.bottom))
                if mi.dwFlags & 1:
                    primaries.append(rect)
                else:
                    others.append(rect)
            return True

        cb = MONITORENUMPROC(_enum_cb)
        user32.EnumDisplayMonitors(None, None, cb, 0)
        areas = primaries + others
        return areas if areas else [LayeredPetWindow.get_work_area()]

    @staticmethod
    def get_cursor_pos() -> tuple[int, int]:
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)

    def pump_events(self):
        msg = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        self.running = False
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self._dib:
            gdi32.SelectObject(self._mem_dc, self._old_bmp)
            gdi32.DeleteObject(self._dib)
            self._dib = None
        if self._mem_dc:
            gdi32.DeleteDC(self._mem_dc)
            self._mem_dc = None

    def _show_context_menu(self):
        if not self.build_menu_items:
            return
        hmenu = user32.CreatePopupMenu()
        radio_groups: dict[str, list[tuple[int, bool]]] = {}
        for item in self.build_menu_items():
            if item.get("separator"):
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
            else:
                grp = item.get("radio_group")
                if grp:
                    user32.AppendMenuW(hmenu, MF_STRING, item["id"], item["label"])
                    radio_groups.setdefault(grp, []).append((int(item["id"]), bool(item.get("checked"))))
                else:
                    flags = MF_STRING | (MF_CHECKED if item.get("checked") else 0)
                    user32.AppendMenuW(hmenu, flags, item["id"], item["label"])
        for entries in radio_groups.values():
            ids = [eid for eid, _ in entries]
            sel = [eid for eid, chk in entries if chk]
            if ids and sel:
                user32.CheckMenuRadioItem(hmenu, min(ids), max(ids), sel[0], 0)
        cx, cy = self.get_cursor_pos()
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_RIGHTBUTTON, cx, cy, 0, self.hwnd, None)
        user32.DestroyMenu(hmenu)
        if cmd and self.on_menu_command:
            self.on_menu_command(int(cmd))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            sx, sy = _signed_word(lparam), _signed_word(lparam >> 16)
            lx, ly = sx - self.win_x, sy - self.win_y
            if self._alpha_map is not None and 0 <= lx < self.width and 0 <= ly < self.height:
                # Let faint outer glow (<22 alpha) pass clicks straight through to desktop icons
                if int(self._alpha_map[ly, lx]) < 22:
                    return HTTRANSPARENT
            return HTCLIENT

        if msg == WM_LBUTTONDOWN:
            user32.SetCapture(hwnd)
            self._dragging = True
            pt = self.get_cursor_pos()
            self._last_drag_pt = pt
            self._last_drag_t = time.perf_counter()
            self._drag_vel = (0.0, 0.0)
            if self.on_drag_start:
                self.on_drag_start(*pt)
            return 0

        if msg == WM_MOUSEMOVE and self._dragging:
            pt = self.get_cursor_pos()
            now = time.perf_counter()
            dt = max(1e-3, now - self._last_drag_t)
            dx, dy = pt[0] - self._last_drag_pt[0], pt[1] - self._last_drag_pt[1]
            vx = 0.65 * self._drag_vel[0] + 0.35 * (dx / dt)
            vy = 0.65 * self._drag_vel[1] + 0.35 * (dy / dt)
            self._drag_vel = (vx, vy)
            self._last_drag_pt = pt
            self._last_drag_t = now
            if self.on_drag_move:
                self.on_drag_move(pt[0], pt[1], dx, dy)
            return 0

        if msg == WM_LBUTTONUP and self._dragging:
            self._dragging = False
            user32.ReleaseCapture()
            pt = self.get_cursor_pos()
            if self.on_drag_end:
                self.on_drag_end(pt[0], pt[1], self._drag_vel[0], self._drag_vel[1])
            return 0

        if msg == WM_LBUTTONDBLCLK:
            if self.on_double_click:
                self.on_double_click(*self.get_cursor_pos())
            return 0

        if msg == WM_RBUTTONUP:
            self._show_context_menu()
            return 0

        if msg == WM_MOUSEWHEEL:
            delta = _signed_word(wparam >> 16) / 120.0
            if self.on_wheel:
                self.on_wheel(delta)
            return 0

        if msg == WM_KEYDOWN and wparam == VK_ESCAPE:
            self.close()
            return 0

        if msg == WM_DESTROY:
            self.running = False
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
