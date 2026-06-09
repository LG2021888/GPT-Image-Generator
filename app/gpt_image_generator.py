#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GPT Image Generator - Stress Test Panel."""
from __future__ import annotations

# PyInstaller fallback: some embedded Python builds miss tkinter during analysis,
# so the tkinter source package is shipped as data under _internal/tkinter.
# Add that directory to sys.path before importing tkinter.
import sys
from pathlib import Path as _BootPath
if getattr(sys, "frozen", False):
    _base = _BootPath(getattr(sys, "_MEIPASS", _BootPath(sys.executable).resolve().parent))
    _tk_parent = _base if (_base / "tkinter" / "__init__.py").exists() else _base / "_internal"
    if (_tk_parent / "tkinter" / "__init__.py").exists():
        sys.path.insert(0, str(_tk_parent))

import base64
import configparser
import json
import math
import mimetypes
import os
import queue
import socket
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, TimeoutError as FutureTimeoutError, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image
except Exception:  # pragma: no cover - 打包环境缺少 Pillow 时仍可运行
    Image = None  # type: ignore[assignment]

APP_TITLE = "GPT 图像生成器"
MAX_INPUT_BYTES = 30 * 1024 * 1024
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_GROK_BASE_URL = "https://api.x.ai/v1"
DEFAULT_GROK_MODEL = "grok-imagine-image-lite"
CONFIG_FILE = "config.ini"
PROMPT_HISTORY_FILE = "prompt_history.json"
IMPORTANT_LOG_FILE = "important.log"
DEFAULT_PROFILE = "默认"
PROMPT_HISTORY_LIMIT = 30
DEFAULT_PROMPT_TEXT = "输入你的图片生成提示词；图生图模式下会结合所选图片进行编辑或参考。"

PRESET_SIZES = [
    "自动（模型自动选择）",
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "1152x2048",
    "3840x2160",
    "2160x3840",
]
IMAGE_COUNT_VALUES = ["1", "2", "3"]
QUALITY_VALUES = ["自动", "低", "中", "高", "标准", "HD"]
QUALITY_TO_API = {"自动": "auto", "低": "low", "中": "medium", "高": "high", "标准": "standard", "HD": "hd"}
API_TO_QUALITY = {v: k for k, v in QUALITY_TO_API.items()}
STYLE_VALUES = ["默认", "鲜明", "自然"]
STYLE_TO_API = {"默认": "", "鲜明": "vivid", "自然": "natural"}
API_TO_STYLE = {v: k for k, v in STYLE_TO_API.items()}
FORMAT_VALUES = ["png", "jpeg", "webp"]
PLATFORM_VALUES = ["OpenAI兼容", "Grok/xAI"]
PLATFORM_TO_API = {"OpenAI兼容": "openai", "Grok/xAI": "grok"}
API_TO_PLATFORM = {v: k for k, v in PLATFORM_TO_API.items()}


@dataclass
class RequestSettings:
    platform: str
    base_url: str
    api_key: str
    mode: str
    image_paths: List[str]
    prompt: str
    size: str
    image_count: int
    quality: str
    style: str
    output_format: str
    compression: int
    model: str
    output_dir: str
    background_after_seconds: int
    hard_timeout_seconds: int
    retry_count: int
    retry_delay: int


class ImageApiError(RuntimeError):
    pass


class StopRequested(RuntimeError):
    pass


def point_in_widget(widget: tk.Widget, x_root: int, y_root: int) -> bool:
    try:
        left = widget.winfo_rootx()
        top = widget.winfo_rooty()
        right = left + widget.winfo_width()
        bottom = top + widget.winfo_height()
    except Exception:
        return False
    return left <= x_root <= right and top <= y_root <= bottom


class MenuSelect(ttk.Frame):
    """稳定的按钮式下拉框：只读按钮 + 箭头按钮 + Toplevel 选项按钮。"""

    def __init__(
        self,
        parent: tk.Widget,
        variable: tk.StringVar,
        values: List[str],
        width: int = 12,
        command: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.variable = variable
        self.values = list(values)
        self.command = command
        self.popup: Optional[tk.Toplevel] = None
        self.button = ttk.Button(self, textvariable=self.variable, width=width, command=self.show_menu, takefocus=False)
        self.button.grid(row=0, column=0, sticky="ew")
        self.arrow_button = ttk.Button(self, text="▼", width=3, command=self.show_menu, takefocus=False)
        self.arrow_button.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.button.bind("<space>", self.show_menu)
        self.button.bind("<Return>", self.show_menu)
        self.button.bind("<Down>", self.show_menu)
        self.arrow_button.bind("<space>", self.show_menu)
        self.arrow_button.bind("<Return>", self.show_menu)
        self.arrow_button.bind("<Down>", self.show_menu)

    def set_values(self, values: List[str]) -> None:
        self.values = list(values)

    def configure_values(self, values: List[str]) -> None:
        self.set_values(values)

    def show_menu(self, event: Optional[tk.Event] = None) -> str:
        if not self.values:
            return "break"
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.lift()
            self.popup.focus_force()
            return "break"
        self.open_dialog()
        return "break"

    def open_dialog(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
            self.popup = None
        self.update_idletasks()
        popup = tk.Toplevel(self)
        self.popup = popup
        popup.title("请选择")
        popup.transient(self.winfo_toplevel())
        popup.attributes("-topmost", True)
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        width = max(self.winfo_width() + 30, 180)
        height = min(max(len(self.values), 1), 12) * 32 + 12
        popup.geometry(f"{width}x{height}+{x}+{y}")

        frame = ttk.Frame(popup, padding=4)
        frame.pack(fill="both", expand=True)

        current = self.variable.get()
        for idx, value in enumerate(self.values[:12]):
            label = f"✓ {value}" if value == current else value
            option = ttk.Button(frame, text=label, command=lambda v=value: self._choose_and_close(v))
            option.grid(row=idx, column=0, sticky="ew", pady=1)
        frame.columnconfigure(0, weight=1)

        def cancel(_event: Optional[tk.Event] = None) -> str:
            self._close_popup()
            return "break"

        def close_on_outside_click(event: tk.Event) -> Optional[str]:
            if not point_in_widget(popup, event.x_root, event.y_root):
                self._close_popup()
                return "break"
            return None

        popup.bind("<ButtonPress-1>", close_on_outside_click, add="+")
        popup.bind("<Escape>", cancel)
        popup.protocol("WM_DELETE_WINDOW", self._close_popup)
        popup.grab_set()
        popup.focus_force()

    def _choose_and_close(self, value: str) -> None:
        self._select(value)
        self._close_popup()

    def _close_popup(self) -> None:
        popup = self.popup
        if popup is not None:
            try:
                if popup.winfo_exists():
                    if popup.grab_current() == popup:
                        popup.grab_release()
                    popup.destroy()
            except Exception:
                pass
        self.popup = None

    def _select(self, value: str) -> None:
        self.variable.set(value)
        if self.command is not None:
            self.command(value)


class ImageApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout

    def generate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/images/generations"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "GPTImageGeneratorStressPanel/1.0",
        }
        return self._request_json(url, data=data, headers=headers)

    def edit(self, fields: Dict[str, Any], image_paths: List[str]) -> Dict[str, Any]:
        url = f"{self.base_url}/images/edits"
        boundary = "----GPTImageBoundary" + uuid4().hex
        body, content_type = build_multipart_body(fields, image_paths, boundary)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": content_type,
            "Accept": "application/json",
            "User-Agent": "GPTImageGeneratorStressPanel/1.0",
        }
        return self._request_json(url, data=body, headers=headers)

    def edit_json(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/images/edits"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "GPTImageGeneratorStressPanel/1.0",
        }
        return self._request_json(url, data=data, headers=headers)

    def _request_json(self, url: str, data: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if not raw:
                    raise ImageApiError(f"HTTP {resp.status}: 空响应")
                try:
                    return json.loads(raw.decode("utf-8"))
                except Exception as exc:
                    preview = raw[:500].decode("utf-8", errors="replace")
                    raise ImageApiError(f"HTTP {resp.status}: 响应不是有效 JSON: {preview}") from exc
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            body = raw.decode("utf-8", errors="replace") if raw else ""
            raise ImageApiError(f"HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise ImageApiError(f"网络超时（超过 {self.timeout}s）") from exc
            raise ImageApiError(f"网络错误: {reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ImageApiError(f"网络超时（超过 {self.timeout}s）") from exc


def build_multipart_body(fields: Dict[str, Any], image_paths: List[str], boundary: str) -> Tuple[bytes, str]:
    chunks: List[bytes] = []

    def add_line(value: str = "") -> None:
        chunks.append(value.encode("utf-8") + b"\r\n")

    for key, value in fields.items():
        if value is None:
            continue
        add_line(f"--{boundary}")
        add_line(f'Content-Disposition: form-data; name="{key}"')
        add_line()
        add_line(str(value))

    for image_path in image_paths:
        path = Path(image_path)
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        add_line(f"--{boundary}")
        add_line(f'Content-Disposition: form-data; name="image"; filename="{path.name}"')
        add_line(f"Content-Type: {mime}")
        add_line()
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")

    add_line(f"--{boundary}--")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def image_file_to_data_url(image_path: str) -> str:
    path = Path(image_path)
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def human_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / 1024 / 1024:.1f}MB"


def compact_json(obj: Any, max_len: int = 1200) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(obj)
    return text if len(text) <= max_len else text[:max_len] + "..."


def normalize_base_url(value: str) -> str:
    value = value.strip() or DEFAULT_BASE_URL
    return value.rstrip("/")


def strip_auto_label(size_value: str) -> str:
    value = size_value.strip()
    return "auto" if value.startswith(("auto", "自动")) else value


def size_label(value: str) -> str:
    return "自动" if value == "auto" else value


def platform_label_to_api(value: str) -> str:
    value = (value or "OpenAI兼容").strip()
    return PLATFORM_TO_API.get(value, value)


def platform_api_to_label(value: str) -> str:
    value = (value or "openai").strip()
    return API_TO_PLATFORM.get(value, value)


def quality_label_to_api(value: str) -> str:
    value = (value or "高").strip()
    return QUALITY_TO_API.get(value, value)


def quality_api_to_label(value: str) -> str:
    value = (value or "high").strip()
    return API_TO_QUALITY.get(value, value)


def style_label_to_api(value: str) -> str:
    value = (value or "默认").strip()
    return STYLE_TO_API.get(value, value)


def style_api_to_label(value: str) -> str:
    value = (value or "").strip()
    return API_TO_STYLE.get(value, value)


def is_grok_platform(platform: str, base_url: str = "") -> bool:
    value = (platform or "").strip().lower()
    if value in {"grok", "xai", "x.ai", "grok/xai"}:
        return True
    host = urllib.parse.urlparse(base_url).netloc.lower()
    return host.endswith("x.ai")


def grok_size_to_aspect_ratio(size: str) -> str:
    """把 WIDTHxHEIGHT 尺寸转换为 xAI/Grok 图片接口的 aspect_ratio。"""
    if size == "auto":
        return "auto"
    try:
        w_text, h_text = size.lower().split("x", 1)
        w, h = int(w_text), int(h_text)
    except Exception:
        return "auto"
    divisor = math.gcd(w, h)
    return f"{w // divisor}:{h // divisor}"


def grok_size_to_resolution(size: str) -> str:
    """xAI 官方当前支持 1k/2k；4K 会请求 2k 后由本地尺寸校正到目标尺寸。"""
    if size == "auto":
        return ""
    try:
        w_text, h_text = size.lower().split("x", 1)
        w, h = int(w_text), int(h_text)
    except Exception:
        return ""
    return "1k" if max(w, h) <= 1024 else "2k"


def should_resize_output(settings: "RequestSettings") -> bool:
    return settings.size != "auto"


def safe_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        num = int(value)
    except Exception:
        return default
    return max(min_value, min(max_value, num))


def app_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_output_dir() -> Path:
    return (app_base_dir() / "output").resolve()


def resolve_initial_output_dir(saved_output_dir: str = "") -> str:
    current_output = default_output_dir()
    saved = str(saved_output_dir or "").strip()
    if current_output.exists():
        return str(current_output)
    if not saved:
        return str(current_output)
    try:
        saved_path = Path(saved).expanduser()
        parts = {part.lower() for part in saved_path.parts}
        if saved_path.name.lower() == "output" and {"gptimagegenerator", "gpt image generator"} & parts:
            return str(current_output)
        if saved_path.exists():
            return str(saved_path.resolve())
    except Exception:
        pass
    return str(current_output)


class GPTImageApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x780")
        self.minsize(920, 760)

        self.config_path = app_base_dir() / CONFIG_FILE
        self.prompt_history_path = app_base_dir() / PROMPT_HISTORY_FILE
        self.important_log_path = app_base_dir() / IMPORTANT_LOG_FILE
        self.log_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.profiles: Dict[str, Dict[str, str]] = {}
        self.prompt_history: List[str] = []
        self.prompt_history_panel: Optional[tk.Frame] = None
        self.prompt_history_rows_frame: Optional[tk.Frame] = None
        self.prompt_history_detail_text: Optional[tk.Text] = None
        self.prompt_history_count_label: Optional[tk.Label] = None
        self.prompt_history_path_label: Optional[tk.Label] = None
        self.selected_images: List[str] = []
        self.running = False
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.progress_animating = False
        self.fake_progress = 0
        self.progress_percent = 0
        self.progress_canvas: Optional[tk.Canvas] = None
        self.progress_text = "0/0 0%"
        self.status_tree: Optional[ttk.Treeview] = None
        self.request_statuses: Dict[int, Dict[str, Any]] = {}
        self.in_flight_count = 0
        self.background_wait_count = 0
        self.background_wait_limit = 0
        self.background_lock = threading.Lock()
        self.closed_forcefully = False
        self.fastest_elapsed: Optional[float] = None
        self.slowest_elapsed: Optional[float] = None
        self.batch_stopping = False
        self.batch_started_at: Optional[float] = None
        self.elapsed_timer_running = False
        self.elapsed_timer_token = 0
        self.batch_prompt_for_history = ""
        self.batch_history_recorded = False
        self.success_count = 0
        self.fail_count = 0
        self.completed_count = 0
        self.total_elapsed = 0.0
        self.total_requests = 1
        self.batch_concurrency = 1
        self.batch_timeout = 80
        self.current_batch_id = 0
        self.background_wait_by_batch: Dict[int, int] = {}
        self.important_log_paths: Dict[int, Path] = {}
        self.important_log_error_reported = False

        self._init_vars()
        self._build_ui()
        self._load_config()
        self._on_mode_change()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_log_queue()

    def _init_vars(self) -> None:
        self.profile_var = tk.StringVar(value=DEFAULT_PROFILE)
        self.profile_name_var = tk.StringVar(value=DEFAULT_PROFILE)
        self.platform_var = tk.StringVar(value=PLATFORM_VALUES[0])
        self.base_url_var = tk.StringVar(value=DEFAULT_BASE_URL)
        self.api_key_var = tk.StringVar(value="")
        self.show_key_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="edit")
        self.size_preset_var = tk.StringVar(value=PRESET_SIZES[0])
        self.custom_size_var = tk.StringVar(value="")
        self.quality_var = tk.StringVar(value="高")
        self.style_var = tk.StringVar(value="默认")
        self.image_count_var = tk.StringVar(value="1")
        self.format_var = tk.StringVar(value="jpeg")
        self.compression_var = tk.IntVar(value=100)
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.total_requests_var = tk.IntVar(value=1)
        self.concurrency_var = tk.IntVar(value=1)
        self.retry_count_var = tk.IntVar(value=0)
        self.retry_delay_var = tk.IntVar(value=3)
        self.background_after_var = tk.IntVar(value=120)
        self.hard_timeout_var = tk.IntVar(value=1800)
        self.timeout_var = self.background_after_var
        self.prompt_mode_var = tk.StringVar(value="repeat")
        default_output = resolve_initial_output_dir()
        self.output_dir_var = tk.StringVar(value=default_output)
        self.stats_vars = {
            "success": tk.StringVar(value="\u6210\u529f:0"),
            "fail": tk.StringVar(value="\u5931\u8d25:0"),
            "running": tk.StringVar(value="\u8fdb\u884c\u4e2d:0"),
            "background": tk.StringVar(value="\u540e\u53f0:0"),
            "rate": tk.StringVar(value="\u6210\u529f\u7387:0%"),
            "avg": tk.StringVar(value="\u5e73\u5747:0.0s"),
            "fastest": tk.StringVar(value="\u6700\u5feb:--"),
            "slowest": tk.StringVar(value="\u6700\u6162:--"),
            "eta": tk.StringVar(value="\u9884\u8ba1\u5269\u4f59:--"),
        }
        self.stats_var = self.stats_vars["success"]
        self.eta_var = self.stats_vars["eta"]
        self.elapsed_var = tk.StringVar(value="耗时:0.0s")

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root = ttk.Frame(self, padding=8)
        root.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(7, weight=1)
        self._build_api_frame(root, 0)
        self._build_mode_frame(root, 1)
        self._build_images_frame(root, 2)
        self._build_prompt_frame(root, 3)
        self._build_params_frame(root, 4)
        self._build_stress_frame(root, 5)
        self._build_control_frame(root, 6)
        self._build_log_frame(root, 7)
        self._build_status_frame(root, 8)

    def _build_api_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="API 配置", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 2))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        ttk.Label(frame, text="配置:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        self.profile_menu = MenuSelect(frame, self.profile_var, [DEFAULT_PROFILE], width=16, command=self._select_profile)
        self.profile_menu.grid(row=0, column=1, sticky="w", pady=2)
        ttk.Label(frame, text="名称:").grid(row=0, column=2, sticky="e", padx=(12, 6), pady=2)
        ttk.Entry(frame, textvariable=self.profile_name_var, width=22).grid(row=0, column=3, sticky="w", pady=2)
        ttk.Button(frame, text="保存/更新", command=self._save_config).grid(row=0, column=4, padx=(8, 0), pady=2)
        ttk.Button(frame, text="删除配置", command=self._delete_profile).grid(row=0, column=5, padx=(8, 0), pady=2)

        ttk.Label(frame, text="平台:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        self.platform_menu = MenuSelect(frame, self.platform_var, PLATFORM_VALUES, width=16, command=lambda _value: self._on_platform_change())
        self.platform_menu.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(frame, text="接口地址:").grid(row=1, column=2, sticky="e", padx=(12, 6), pady=2)
        ttk.Entry(frame, textvariable=self.base_url_var).grid(row=1, column=3, columnspan=3, sticky="ew", pady=2)
        ttk.Label(frame, text="API Key:").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        self.api_key_entry = ttk.Entry(frame, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=2, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Checkbutton(frame, text="显示", variable=self.show_key_var, command=self._toggle_key).grid(row=2, column=4, padx=8)

    def _build_mode_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="模式", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        ttk.Radiobutton(frame, text="文生图", variable=self.mode_var, value="generate", command=self._on_mode_change).pack(side="left", padx=(4, 18))
        ttk.Radiobutton(frame, text="图生图（图+文）", variable=self.mode_var, value="edit", command=self._on_mode_change).pack(side="left")

    def _build_images_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="输入图片（总大小 <= 30MB，文生图无需选择）", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        self.image_label_var = tk.StringVar(value="未选择图片")
        self.image_entry = ttk.Entry(frame, textvariable=self.image_label_var, state="readonly")
        self.image_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.image_entry.bind("<Delete>", self._clear_images_from_entry)
        self.image_entry.bind("<BackSpace>", self._clear_images_from_entry)
        self.image_button = ttk.Button(frame, text="选择图片", command=self._select_images)
        self.image_button.grid(row=0, column=1)
        self.clear_images_button = ttk.Button(frame, text="清除图片", command=self._clear_images, state="disabled")
        self.clear_images_button.grid(row=0, column=2, padx=(8, 0))

    def _build_prompt_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="提示词", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        mode_row = ttk.Frame(frame)
        mode_row.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(mode_row, text="提示词模式:").pack(side="left")
        ttk.Radiobutton(mode_row, text="单提示词重复", variable=self.prompt_mode_var, value="repeat").pack(side="left", padx=(8, 12))
        ttk.Radiobutton(mode_row, text="每行一个提示词", variable=self.prompt_mode_var, value="lines").pack(side="left")
        self.prompt_text = tk.Text(frame, height=3, wrap="word", undo=True)
        self.prompt_text.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.prompt_history_button = ttk.Button(frame, text="历史", width=8, command=self._show_prompt_history)
        self.prompt_history_button.grid(row=1, column=1, sticky="ns")
        self.prompt_text.insert("1.0", DEFAULT_PROMPT_TEXT)
        self._build_prompt_history_panel(frame)

    def _build_prompt_history_panel(self, parent: ttk.Frame) -> None:
        self.prompt_history_panel = tk.Frame(parent, bd=1, relief="solid", padx=6, pady=6)
        self.prompt_history_panel.columnconfigure(0, weight=1)

        header = tk.Frame(self.prompt_history_panel)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        header.columnconfigure(0, weight=1)
        self.prompt_history_count_label = tk.Label(header, text="历史记录列表（0 条）")
        self.prompt_history_count_label.grid(row=0, column=0, sticky="w")
        tk.Button(header, text="刷新", width=6, command=self._reload_prompt_history_panel).grid(row=0, column=1, padx=(8, 0))
        tk.Button(header, text="关闭", width=6, command=self._hide_prompt_history_panel).grid(row=0, column=2, padx=(8, 0))
        self.prompt_history_path_label = tk.Label(header, text="", anchor="w", justify="left", fg="#555555")
        self.prompt_history_path_label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(3, 0))

        rows_container = tk.Frame(self.prompt_history_panel, bd=1, relief="groove")
        rows_container.grid(row=1, column=0, sticky="nsew")
        rows_container.columnconfigure(0, weight=1)
        rows_container.rowconfigure(0, weight=1)

        self.prompt_history_canvas = tk.Canvas(rows_container, height=220, highlightthickness=0)
        self.prompt_history_canvas.grid(row=0, column=0, sticky="nsew")
        self.prompt_history_scrollbar = ttk.Scrollbar(rows_container, orient="vertical", command=self.prompt_history_canvas.yview)
        self.prompt_history_scrollbar.grid(row=0, column=1, sticky="ns")
        self.prompt_history_canvas.configure(yscrollcommand=self.prompt_history_scrollbar.set)

        self.prompt_history_rows_frame = tk.Frame(self.prompt_history_canvas)
        self._prompt_history_rows_window = self.prompt_history_canvas.create_window(
            (0, 0), window=self.prompt_history_rows_frame, anchor="nw"
        )

        def _on_rows_configure(_event):
            self.prompt_history_canvas.configure(scrollregion=self.prompt_history_canvas.bbox("all"))

        def _on_canvas_configure(event):
            self.prompt_history_canvas.itemconfigure(self._prompt_history_rows_window, width=event.width)

        self.prompt_history_rows_frame.bind("<Configure>", _on_rows_configure)
        self.prompt_history_canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            self.prompt_history_canvas.yview_scroll(int(-event.delta / 120), "units")

        def _bind_wheel(_e):
            self.prompt_history_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_wheel(_e):
            self.prompt_history_canvas.unbind_all("<MouseWheel>")

        self.prompt_history_canvas.bind("<Enter>", _bind_wheel)
        self.prompt_history_canvas.bind("<Leave>", _unbind_wheel)

        self.prompt_history_detail_text = tk.Text(self.prompt_history_panel, height=3, wrap="word")
        self.prompt_history_detail_text.grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def _build_params_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="参数", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(7, weight=1)
        ttk.Label(frame, text="尺寸预设:").grid(row=0, column=0, sticky="w", pady=3)
        self.size_menu = MenuSelect(frame, self.size_preset_var, PRESET_SIZES, width=22)
        self.size_menu.grid(row=0, column=1, sticky="w", padx=(4, 18), pady=3)
        ttk.Label(frame, text="自定义尺寸:").grid(row=0, column=2, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.custom_size_var, width=13).grid(row=0, column=3, sticky="w", padx=(4, 8), pady=3)
        ttk.Label(frame, text="(宽高须为 16 的倍数，比例 <= 3:1)").grid(row=0, column=4, sticky="w", pady=3)
        ttk.Label(frame, text="质量:").grid(row=1, column=0, sticky="w", pady=3)
        self.quality_menu = MenuSelect(frame, self.quality_var, QUALITY_VALUES, width=8)
        self.quality_menu.grid(row=1, column=1, sticky="w", padx=(4, 18), pady=3)
        ttk.Label(frame, text="格式:").grid(row=1, column=2, sticky="w", pady=3)
        self.format_menu = MenuSelect(frame, self.format_var, FORMAT_VALUES, width=8)
        self.format_menu.grid(row=1, column=3, sticky="w", padx=(4, 18), pady=3)
        ttk.Label(frame, text="压缩(jpeg/webp):").grid(row=1, column=4, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=0, to=100, textvariable=self.compression_var, width=6).grid(row=1, column=5, sticky="w", padx=(4, 0), pady=3)
        ttk.Label(frame, text="张数:").grid(row=1, column=6, sticky="w", padx=(18, 0), pady=3)
        self.image_count_menu = MenuSelect(frame, self.image_count_var, IMAGE_COUNT_VALUES, width=5)
        self.image_count_menu.grid(row=1, column=7, sticky="w", padx=(4, 0), pady=3)
        ttk.Label(frame, text="模型:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.model_var, width=22).grid(row=2, column=1, sticky="w", padx=(4, 18), pady=3)
        ttk.Label(frame, text="风格:").grid(row=2, column=2, sticky="w", pady=3)
        self.style_menu = MenuSelect(frame, self.style_var, STYLE_VALUES, width=8)
        self.style_menu.grid(row=2, column=3, sticky="w", padx=(4, 18), pady=3)

    def _build_stress_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="压力测试", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(5, weight=1)
        ttk.Label(frame, text="总请求数:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=1, to=10000, textvariable=self.total_requests_var, width=8).grid(row=0, column=1, sticky="w", padx=(4, 16), pady=3)
        ttk.Label(frame, text="并发线程数:").grid(row=0, column=2, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=1, to=100, textvariable=self.concurrency_var, width=8).grid(row=0, column=3, sticky="w", padx=(4, 16), pady=3)
        ttk.Label(frame, text="输出目录:").grid(row=0, column=4, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.output_dir_var).grid(row=0, column=5, sticky="ew", padx=(4, 6), pady=3)
        ttk.Button(frame, text="...", width=4, command=self._select_output_dir).grid(row=0, column=6, pady=3)
        ttk.Button(frame, text="打开输出目录", command=self._open_output_dir).grid(row=0, column=7, padx=(8, 0), pady=3)
        ttk.Label(frame, text="失败重试:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=0, to=5, textvariable=self.retry_count_var, width=8).grid(row=1, column=1, sticky="w", padx=(4, 16), pady=3)
        ttk.Label(frame, text="重试间隔(s):").grid(row=1, column=2, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=0, to=60, textvariable=self.retry_delay_var, width=8).grid(row=1, column=3, sticky="w", padx=(4, 16), pady=3)
        wait_frame = ttk.Frame(frame)
        wait_frame.grid(row=1, column=4, columnspan=4, sticky="w", pady=3)
        ttk.Label(wait_frame, text="\u540e\u53f0\u7b49\u5f85\u9608\u503c(\u79d2):").pack(side="left")
        ttk.Spinbox(wait_frame, from_=1, to=1800, textvariable=self.background_after_var, width=8).pack(side="left", padx=(4, 14))
        ttk.Label(wait_frame, text="\u540e\u53f0\u6700\u957f\u7b49\u5f85(\u79d2):").pack(side="left")
        ttk.Spinbox(wait_frame, from_=1, to=7200, textvariable=self.hard_timeout_var, width=8).pack(side="left", padx=(4, 0))

    def _build_control_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(frame, text="开始生成", command=self._start)
        self.start_button.grid(row=0, column=0, sticky="w")
        self.stop_button = ttk.Button(frame, text="停止", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(12, 18))
        self.progress_canvas = tk.Canvas(frame, height=18, highlightthickness=0, bd=0)
        self.progress_canvas.grid(row=0, column=2, sticky="ew", padx=(0, 12))
        self.progress_canvas.bind("<Configure>", lambda _event: self._draw_progress())
        ttk.Label(frame, textvariable=self.elapsed_var).grid(row=0, column=3, sticky="e")
        stats_frame = ttk.Frame(frame)
        stats_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=(0, 0), pady=(6, 0))
        stat_keys = ("success", "fail", "running", "background", "rate", "avg", "fastest", "slowest", "eta")
        for stat_col, key in enumerate(stat_keys):
            stats_frame.columnconfigure(stat_col, weight=1, uniform="stats")
            anchor = "e" if key == "eta" else "center"
            ttk.Label(stats_frame, textvariable=self.stats_vars[key], anchor=anchor).grid(
                row=0, column=stat_col, sticky="ew", padx=3
            )

    def _build_status_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="请求状态", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        columns = ("idx", "status", "elapsed", "retry", "result")
        self.status_tree = ttk.Treeview(frame, columns=columns, show="headings", height=3)
        headings = {"idx": "#", "status": "状态", "elapsed": "耗时", "retry": "重试", "result": "结果"}
        widths = {"idx": 48, "status": 80, "elapsed": 70, "retry": 70, "result": 640}
        for col in columns:
            self.status_tree.heading(col, text=headings[col])
            self.status_tree.column(col, width=widths[col], minwidth=40, anchor="w", stretch=(col == "result"))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.status_tree.yview)
        self.status_tree.configure(yscrollcommand=scroll.set)
        self.status_tree.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")

    def _build_log_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="日志", padding=6)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(frame, height=7, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    def _toggle_key(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _on_platform_change(self) -> None:
        if self.running:
            return
        platform = platform_label_to_api(self.platform_var.get())
        current_base = normalize_base_url(self.base_url_var.get())
        current_model = self.model_var.get().strip()
        if platform == "grok":
            if current_base == DEFAULT_BASE_URL:
                self.base_url_var.set(DEFAULT_GROK_BASE_URL)
            if not current_model or current_model == DEFAULT_MODEL:
                self.model_var.set(DEFAULT_GROK_MODEL)
            self._enqueue_log("已切换到 Grok/xAI：使用 OpenAI 兼容接口 /images/generations；图生图接口取决于服务商是否支持。")
        else:
            if current_base == DEFAULT_GROK_BASE_URL:
                self.base_url_var.set(DEFAULT_BASE_URL)
            if current_model == DEFAULT_GROK_MODEL:
                self.model_var.set(DEFAULT_MODEL)

    def _on_mode_change(self) -> None:
        if self.mode_var.get() == "generate":
            if hasattr(self, "image_entry"):
                self.image_entry.configure(state="readonly")
            if hasattr(self, "image_button"):
                self.image_button.configure(state="disabled")
        else:
            if hasattr(self, "image_entry"):
                self.image_entry.configure(state="readonly")
            if hasattr(self, "image_button"):
                self.image_button.configure(state="normal")
        self._refresh_image_label()

    def _show_prompt_history(self) -> None:
        if self.prompt_history_panel is None:
            return
        if self.prompt_history_panel.winfo_ismapped():
            self._hide_prompt_history_panel()
            return
        self.prompt_history_panel.grid(row=2, column=0, columnspan=2, sticky="ew")
        self._reload_prompt_history_panel()
        self.prompt_history_panel.update_idletasks()
        if hasattr(self, "prompt_history_canvas") and self.prompt_history_canvas is not None:
            self.prompt_history_canvas.yview_moveto(0.0)

    def _hide_prompt_history_panel(self) -> None:
        if self.prompt_history_panel is not None:
            self.prompt_history_panel.grid_remove()

    def _prompt_history_preview(self, prompt: str) -> str:
        preview = " ".join(prompt.split())
        if len(preview) > 88:
            return preview[:85] + "..."
        return preview

    def _set_prompt_history_detail(self, text: str) -> None:
        if self.prompt_history_detail_text is None:
            return
        self.prompt_history_detail_text.configure(state="normal")
        self.prompt_history_detail_text.delete("1.0", "end")
        self.prompt_history_detail_text.insert("1.0", text)
        self.prompt_history_detail_text.configure(state="disabled")

    def _show_full_prompt_on_hover(self, prompt: str) -> None:
        self._set_prompt_history_detail(prompt)

    def _bind_prompt_history_hover(self, widget: tk.Widget, prompt: str) -> None:
        widget.bind("<Enter>", lambda _event, text=prompt: self._show_full_prompt_on_hover(text))

    def _fill_prompt_history_panel(self, history: List[str]) -> None:
        self.prompt_history = history
        if self.prompt_history_count_label is not None:
            self.prompt_history_count_label.configure(text=f"历史记录列表（{len(history)} 条）")
        if self.prompt_history_path_label is not None:
            self.prompt_history_path_label.configure(text=f"历史文件: {self.prompt_history_path}")
        if self.prompt_history_rows_frame is None:
            return

        for child in self.prompt_history_rows_frame.winfo_children():
            child.destroy()
        self.prompt_history_rows_frame.configure(height=40)

        if not history:
            empty_label = tk.Label(
                self.prompt_history_rows_frame,
                text="暂无提示词历史",
                anchor="w",
                padx=6,
                pady=8,
            )
            empty_label.pack(fill="x", expand=True)
            self._set_prompt_history_detail("暂无提示词历史")
            self.prompt_history_rows_frame.update_idletasks()
            self._enqueue_log("提示词历史: 已渲染 0 个按钮（无历史）")
            return

        for idx, prompt in enumerate(history):
            row = tk.Frame(self.prompt_history_rows_frame)
            row.pack(fill="x", padx=4, pady=3)
            row.columnconfigure(0, weight=1)
            row.columnconfigure(1, weight=0)
            preview = f"{idx + 1}. {self._prompt_history_preview(prompt)}"
            prompt_button = tk.Button(
                row,
                text=preview,
                anchor="w",
                padx=8,
                pady=4,
                relief="raised",
                command=lambda i=idx: self._use_prompt_history_index(i),
            )
            prompt_button.grid(row=0, column=0, sticky="ew")
            delete_button = tk.Button(
                row,
                text="删除",
                width=6,
                pady=4,
                relief="raised",
                command=lambda i=idx: self._delete_prompt_history_index(i),
            )
            delete_button.grid(row=0, column=1, sticky="e", padx=(6, 0))
            self._bind_prompt_history_hover(prompt_button, prompt)
            self._bind_prompt_history_hover(delete_button, prompt)

        self._set_prompt_history_detail("点击历史内容回填；点击“删除”移除该条历史。")
        self.prompt_history_rows_frame.update_idletasks()
        if self.prompt_history_panel is not None:
            self.prompt_history_panel.update_idletasks()
        self._enqueue_log(f"提示词历史: 已渲染 {len(history)} 个按钮")

    def _reload_prompt_history_panel(self) -> None:
        try:
            items = self._read_prompt_history_items_for_window()
            self._enqueue_log(f"提示词历史: 读取到 {len(items)} 条")
            self._fill_prompt_history_panel(items)
        except Exception as exc:
            import traceback
            self._enqueue_log(f"提示词历史: 渲染失败 {type(exc).__name__}: {exc}")
            self._enqueue_log(traceback.format_exc())

    def _delete_prompt_history_index(self, index: int) -> None:
        if index < 0 or index >= len(self.prompt_history):
            return
        removed = self.prompt_history[index]
        self.prompt_history = self.prompt_history[:index] + self.prompt_history[index + 1 :]
        try:
            self._write_prompt_history_to_disk(self.prompt_history)
            self._fill_prompt_history_panel(self.prompt_history)
            self._set_prompt_history_detail(f"已删除: {self._prompt_history_preview(removed)}")
        except Exception as exc:
            self._enqueue_log(f"删除提示词历史失败: {exc}")

    def _apply_prompt_history(self, index: int) -> None:
        if index < 0 or index >= len(self.prompt_history):
            return
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", self.prompt_history[index])
        self.prompt_text.focus_set()

    def _use_prompt_history_value(self, prompt: str) -> None:
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", prompt)
        self.prompt_text.focus_set()

    def _use_prompt_history_index(self, index: int) -> str:
        self._apply_prompt_history(index)
        self._hide_prompt_history_panel()
        return "break"

    def _refresh_prompt_history_window(self) -> None:
        if self.prompt_history_panel is not None and self.prompt_history_panel.winfo_ismapped():
            self._reload_prompt_history_panel()

    def _refresh_prompt_history_from_window(self) -> None:
        self._refresh_prompt_history_window()

    def _read_prompt_history_items_for_window(self) -> List[str]:
        history, _raw_count, error = self._read_prompt_history_for_window()
        self.prompt_history = history
        if error:
            self._enqueue_log(f"读取提示词历史失败: {error}")
        return history

    def _read_prompt_history_for_window(self) -> Tuple[List[str], int, str]:
        if self.prompt_history_path.exists():
            try:
                raw = self.prompt_history_path.read_text(encoding="utf-8").strip()
            except Exception as exc:
                return [], 0, f"读取 {PROMPT_HISTORY_FILE} 失败: {exc}"
            if not raw:
                return [], 0, f"{PROMPT_HISTORY_FILE} 为空"
            return self._parse_prompt_history_raw(raw)
        # 兼容老 config.ini 中残留的 [prompt_history]
        if not self.config_path.exists():
            return [], 0, f"{PROMPT_HISTORY_FILE} 和 config.ini 都不存在"
        cfg = configparser.ConfigParser(interpolation=None)
        try:
            cfg.read(self.config_path, encoding="utf-8")
        except Exception as exc:
            return [], 0, f"读取 config.ini 失败: {exc}"
        if not cfg.has_section("prompt_history"):
            return [], 0, f"{PROMPT_HISTORY_FILE} 不存在，config.ini 也没有 [prompt_history] 区段"
        raw = cfg.get("prompt_history", "items", fallback="").strip()
        if not raw:
            return [], 0, "items 为空"
        return self._parse_prompt_history_raw(raw)

    def _parse_prompt_history_raw(self, raw: str) -> Tuple[List[str], int, str]:
        try:
            data = json.loads(raw)
        except Exception as exc:
            repaired = self._escape_json_string_newlines(raw)
            try:
                data = json.loads(repaired)
            except Exception:
                return [], 0, f"items JSON 解析失败: {exc}"
        if not isinstance(data, list):
            return [], 0, "items 不是 JSON 数组"

        return self._normalize_prompt_history(data), len(data), ""

    def _escape_json_string_newlines(self, raw: str) -> str:
        result: List[str] = []
        in_string = False
        escaped = False
        for ch in raw:
            if escaped:
                result.append(ch)
                escaped = False
                continue
            if ch == "\\":
                result.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch in {"\n", "\r"}:
                result.append("\\n")
                continue
            result.append(ch)
        return "".join(result)

    def _read_prompt_history_raw_from_broken_config(self) -> str:
        try:
            lines = self.config_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return ""

        in_history = False
        parts: List[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                if in_history:
                    break
                in_history = stripped.lower() == "[prompt_history]"
                continue
            if not in_history:
                continue
            if not parts:
                if stripped.startswith("items"):
                    _key, _sep, value = line.partition("=")
                    parts.append(value.strip())
                continue
            parts.append(line)
        return "\n".join(parts).strip()

    def _close_prompt_history_window(self) -> None:
        self._hide_prompt_history_panel()

    def _record_prompt_history(self, prompt: str) -> None:
        prompt = prompt.strip()
        if not prompt or prompt == DEFAULT_PROMPT_TEXT:
            return
        if self.prompt_history and self.prompt_history[0] == prompt:
            return
        self.prompt_history = self._normalize_prompt_history([prompt] + self.prompt_history)
        try:
            self._write_prompt_history_to_disk(self.prompt_history)
            self._refresh_prompt_history_window()
        except Exception as exc:
            self._enqueue_log(f"保存提示词历史失败: {exc}")

    def _record_started_prompt_history(self, prompts: List[str], raw_prompt: str) -> None:
        if self.prompt_mode_var.get() == "lines":
            items = [prompt.strip() for prompt in prompts if prompt.strip()]
        else:
            items = [raw_prompt.strip()]
        items = [item for item in items if item and item != DEFAULT_PROMPT_TEXT]
        if not items:
            return
        new_history = self._normalize_prompt_history(items + self.prompt_history)
        if new_history == self.prompt_history:
            return
        self.prompt_history = new_history
        try:
            self._write_prompt_history_to_disk(self.prompt_history)
            self._refresh_prompt_history_window()
        except Exception as exc:
            self._enqueue_log(f"\u4fdd\u5b58\u63d0\u793a\u8bcd\u5386\u53f2\u5931\u8d25: {exc}")

    def _record_batch_prompt_history_once(self, prompt: str = "") -> None:
        prompt = (self.batch_prompt_for_history or prompt).strip()
        if self.batch_history_recorded or not prompt or prompt == DEFAULT_PROMPT_TEXT:
            return
        self._record_prompt_history(prompt)
        self.batch_prompt_for_history = prompt
        self.batch_history_recorded = True

    def _normalize_prompt_history(self, items: List[str]) -> List[str]:
        history: List[str] = []
        for item in items:
            if not isinstance(item, str):
                continue
            prompt = item.strip()
            if not prompt or prompt == DEFAULT_PROMPT_TEXT:
                continue
            if prompt in history:
                continue
            history.append(prompt)
            if len(history) >= PROMPT_HISTORY_LIMIT:
                break
        return history

    def _sync_prompt_history_from_config(self) -> None:
        if not self.config_path.exists():
            return
        cfg = configparser.ConfigParser(interpolation=None)
        try:
            cfg.read(self.config_path, encoding="utf-8")
        except Exception as exc:
            self._enqueue_log(f"同步提示词历史失败: {exc}")
            return
        loaded = self._load_prompt_history(cfg)
        self.prompt_history = loaded
        self._refresh_prompt_history_window()

    def _load_config(self) -> None:
        cfg = configparser.ConfigParser(interpolation=None)
        loaded = False
        try:
            if self.config_path.exists():
                cfg.read(self.config_path, encoding="utf-8")
                loaded = True
        except Exception as exc:
            self._enqueue_log(f"加载配置失败: {exc}")

        app_sec = cfg["app"] if cfg.has_section("app") else {}
        profiles: Dict[str, Dict[str, str]] = {}
        for section in cfg.sections():
            if not section.startswith("profile:"):
                continue
            name = section.split(":", 1)[1].strip() or DEFAULT_PROFILE
            sec = cfg[section]
            profiles[name] = {
                "platform": sec.get("platform", app_sec.get("platform", "openai")),
                "base_url": sec.get("base_url", DEFAULT_BASE_URL),
                "api_key": sec.get("api_key", ""),
                "model": sec.get("model", DEFAULT_MODEL),
            }

        # Backward-compatible migration from the old single-profile [app] format.
        if not profiles:
            profiles[DEFAULT_PROFILE] = {
                "platform": app_sec.get("platform", "openai"),
                "base_url": app_sec.get("base_url", DEFAULT_BASE_URL),
                "api_key": app_sec.get("api_key", ""),
                "model": app_sec.get("model", DEFAULT_MODEL),
            }

        self.profiles = profiles
        current = app_sec.get("current_profile", app_sec.get("profile", DEFAULT_PROFILE)).strip() or DEFAULT_PROFILE
        if current not in self.profiles:
            current = next(iter(self.profiles))

        self.output_dir_var.set(resolve_initial_output_dir(app_sec.get("output_dir", self.output_dir_var.get())))
        saved_size = app_sec.get("size_preset", PRESET_SIZES[0])
        self.size_preset_var.set(PRESET_SIZES[0] if saved_size.startswith(("auto", "自动")) else saved_size)
        self.custom_size_var.set(app_sec.get("custom_size", ""))
        self.quality_var.set(quality_api_to_label(app_sec.get("quality", "high")))
        self.style_var.set(style_api_to_label(app_sec.get("style", "")))
        self.image_count_var.set(str(safe_int(app_sec.get("image_count", 1), 1, 1, 3)))
        self.format_var.set(app_sec.get("output_format", "jpeg"))
        self.compression_var.set(safe_int(app_sec.get("compression", 100), 100, 0, 100))
        self.mode_var.set(app_sec.get("mode", "edit"))
        self.background_after_var.set(safe_int(app_sec.get("background_after_seconds", app_sec.get("timeout", 120)), 120, 1, 1800))
        self.hard_timeout_var.set(safe_int(app_sec.get("hard_timeout_seconds", 1800), 1800, 1, 7200))
        self.prompt_history = self._load_prompt_history(cfg)

        self._refresh_profile_menu(current)
        self._apply_profile(current)
        if loaded:
            self._enqueue_log(f"已从 {self.config_path.name} 加载配置（当前 API 配置: {current}）")
        else:
            self._enqueue_log("未找到 config.ini，已使用默认配置")

    def _load_prompt_history(self, cfg: configparser.ConfigParser) -> List[str]:
        # 1) 优先读独立 json 文件
        if self.prompt_history_path.exists():
            try:
                raw = self.prompt_history_path.read_text(encoding="utf-8").strip()
                if not raw:
                    return []
                history, _n, error = self._parse_prompt_history_raw(raw)
                if error:
                    self._enqueue_log(f"提示词历史格式无效，已忽略: {error}")
                return history
            except Exception as exc:
                self._enqueue_log(f"读取 {PROMPT_HISTORY_FILE} 失败: {exc}")
                return []
        # 2) fallback：从 INI [prompt_history] 迁移
        if cfg.has_section("prompt_history"):
            raw = cfg.get("prompt_history", "items", fallback="[]").strip()
            history, _n, error = self._parse_prompt_history_raw(raw) if raw else ([], 0, "")
            if error:
                self._enqueue_log(f"提示词历史格式无效，已忽略: {error}")
            if history:
                try:
                    self._write_prompt_history_to_disk(history)
                    self._enqueue_log(f"已从 config.ini 迁移 {len(history)} 条提示词历史到 {PROMPT_HISTORY_FILE}")
                except Exception as exc:
                    self._enqueue_log(f"迁移提示词历史失败: {exc}")
            return history
        return []

    def _write_prompt_history_to_disk(self, history: List[str]) -> None:
        data = history[:PROMPT_HISTORY_LIMIT]
        self.prompt_history_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_config(self) -> None:
        name = self.profile_name_var.get().strip() or self.profile_var.get().strip() or DEFAULT_PROFILE
        name = name.replace("\n", " ").replace("\r", " ").strip() or DEFAULT_PROFILE
        self.profiles[name] = {
            "platform": platform_label_to_api(self.platform_var.get()),
            "base_url": normalize_base_url(self.base_url_var.get()),
            "api_key": self.api_key_var.get().strip(),
            "model": self.model_var.get().strip() or DEFAULT_MODEL,
        }
        self.profile_var.set(name)
        self.profile_name_var.set(name)
        try:
            self._write_config()
            self._refresh_profile_menu(name)
            self._enqueue_log(f"配置「{name}」已保存到 {self.config_path}")
            messagebox.showinfo("保存配置", f"配置「{name}」已保存。")
        except Exception as exc:
            messagebox.showerror("保存配置失败", str(exc))

    def _write_config(self) -> None:
        cfg = configparser.ConfigParser(interpolation=None)
        self.prompt_history = self._normalize_prompt_history(self.prompt_history)
        cfg["app"] = {
            "current_profile": self.profile_var.get().strip() or DEFAULT_PROFILE,
            "output_dir": self.output_dir_var.get().strip(),
            "size_preset": self.size_preset_var.get(),
            "custom_size": self.custom_size_var.get().strip(),
            "quality": quality_label_to_api(self.quality_var.get()),
            "style": style_label_to_api(self.style_var.get()),
            "image_count": str(safe_int(self.image_count_var.get(), 1, 1, 3)),
            "output_format": self.format_var.get(),
            "compression": str(safe_int(self.compression_var.get(), 100, 0, 100)),
            "mode": self.mode_var.get(),
            "background_after_seconds": str(safe_int(self.background_after_var.get(), 120, 1, 1800)),
            "hard_timeout_seconds": str(safe_int(self.hard_timeout_var.get(), 1800, 1, 7200)),
        }
        if not self.profiles:
            self.profiles[DEFAULT_PROFILE] = {
                "platform": platform_label_to_api(self.platform_var.get()),
                "base_url": normalize_base_url(self.base_url_var.get()),
                "api_key": self.api_key_var.get().strip(),
                "model": self.model_var.get().strip() or DEFAULT_MODEL,
            }
        for name, profile in self.profiles.items():
            section = f"profile:{name}"
            cfg[section] = {
                "platform": profile.get("platform", "openai"),
                "base_url": profile.get("base_url", DEFAULT_BASE_URL),
                "api_key": profile.get("api_key", ""),
                "model": profile.get("model", DEFAULT_MODEL),
            }
        with self.config_path.open("w", encoding="utf-8") as f:
            cfg.write(f)

    def _refresh_profile_menu(self, selected: Optional[str] = None) -> None:
        names = list(self.profiles.keys()) or [DEFAULT_PROFILE]
        selected = selected if selected in names else names[0]
        self.profile_var.set(selected)
        self.profile_name_var.set(selected)
        if hasattr(self, "profile_menu"):
            self.profile_menu.set_values(names)

    def _select_profile(self, name: str) -> None:
        self._apply_profile(name)
        self._enqueue_log(f"已切换 API 配置: {name}")

    def _apply_profile(self, name: str) -> None:
        profile = self.profiles.get(name)
        if profile is None:
            return
        self.profile_var.set(name)
        self.profile_name_var.set(name)
        self.platform_var.set(platform_api_to_label(profile.get("platform", "openai")))
        self.base_url_var.set(profile.get("base_url", DEFAULT_BASE_URL))
        self.api_key_var.set(profile.get("api_key", ""))
        self.model_var.set(profile.get("model", DEFAULT_MODEL))

    def _delete_profile(self) -> None:
        name = self.profile_var.get().strip()
        if len(self.profiles) <= 1:
            messagebox.showinfo("删除配置", "至少保留一个 API 配置。")
            return
        if name not in self.profiles:
            return
        if not messagebox.askyesno("删除配置", f"确定删除 API 配置「{name}」吗？"):
            return
        del self.profiles[name]
        next_name = next(iter(self.profiles))
        self._refresh_profile_menu(next_name)
        self._apply_profile(next_name)
        try:
            self._write_config()
            self._enqueue_log(f"已删除 API 配置: {name}")
        except Exception as exc:
            messagebox.showerror("删除配置失败", str(exc))

    def _masked_key(self) -> str:
        key = self.api_key_var.get().strip()
        if not key:
            return "空"
        if len(key) <= 8:
            return "*" * len(key)
        return key[:3] + "*" * max(4, min(12, len(key) - 6)) + key[-3:]

    def _select_images(self) -> None:
        if self.mode_var.get() == "generate":
            messagebox.showinfo("文生图模式", "文生图模式不需要选择图片。")
            return
        paths = filedialog.askopenfilenames(title="选择输入图片", filetypes=[("图片文件", "*.png *.jpg *.jpeg *.webp *.gif"), ("全部文件", "*.*")])
        if not paths:
            return
        total = 0
        valid: List[str] = []
        for p in paths:
            try:
                size = Path(p).stat().st_size
            except OSError:
                continue
            total += size
            valid.append(p)
        if total > MAX_INPUT_BYTES:
            messagebox.showerror("图片过大", f"输入图片总大小 {human_size(total)}，超过 30MB 限制。")
            return
        self.selected_images = valid
        self._refresh_image_label()
        self._enqueue_log(f"已选择 {len(valid)} 张图片，总大小 {human_size(total)}")

    def _clear_images_from_entry(self, _event: Optional[tk.Event] = None) -> str:
        self._clear_images()
        return "break"

    def _clear_images(self) -> None:
        if not self.selected_images:
            return
        self.selected_images = []
        self._refresh_image_label()
        self._enqueue_log("已清除输入图片")

    def _refresh_image_label(self) -> None:
        total = sum(Path(p).stat().st_size for p in self.selected_images if Path(p).exists())
        if self.mode_var.get() == "generate":
            if self.selected_images:
                self.image_label_var.set(f"文生图模式无需选择图片（已选 {len(self.selected_images)} 张，生成时忽略）")
            else:
                self.image_label_var.set("文生图模式无需选择图片")
            if hasattr(self, "clear_images_button"):
                self.clear_images_button.configure(state="normal" if self.selected_images else "disabled")
            return
        if self.selected_images:
            self.image_label_var.set(f"已选择 {len(self.selected_images)} 张图片，合计 {human_size(total)}")
        else:
            self.image_label_var.set("未选择图片")
        if hasattr(self, "clear_images_button"):
            self.clear_images_button.configure(state="normal" if self.selected_images else "disabled")

    def _select_output_dir(self) -> None:
        path = filedialog.askdirectory(title="\u9009\u62e9\u8f93\u51fa\u76ee\u5f55", initialdir=self.output_dir_var.get() or str(default_output_dir()))
        if path:
            self.output_dir_var.set(path)

    def _open_output_dir(self) -> None:
        path = Path(self.output_dir_var.get().strip() or default_output_dir()).resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("打开输出目录失败", str(exc))

    def _current_settings(self) -> RequestSettings:
        custom_size = self.custom_size_var.get().strip()
        size = custom_size if custom_size else strip_auto_label(self.size_preset_var.get())
        mode = self.mode_var.get()
        platform = platform_label_to_api(self.platform_var.get())
        prompt = self.prompt_text.get("1.0", "end").strip()
        if prompt == DEFAULT_PROMPT_TEXT:
            prompt = ""
        return RequestSettings(
            platform=platform,
            base_url=normalize_base_url(self.base_url_var.get()),
            api_key=self.api_key_var.get().strip(),
            mode=mode,
            image_paths=[] if mode == "generate" else list(self.selected_images),
            prompt=prompt,
            size=size,
            image_count=safe_int(self.image_count_var.get(), 1, 1, 3),
            quality=quality_label_to_api(self.quality_var.get()),
            style=style_label_to_api(self.style_var.get()),
            output_format=self.format_var.get().strip() or "png",
            compression=safe_int(self.compression_var.get(), 100, 0, 100),
            model=self.model_var.get().strip() or DEFAULT_MODEL,
            output_dir=self.output_dir_var.get().strip() or str(default_output_dir()),
            background_after_seconds=safe_int(self.background_after_var.get(), 120, 1, 1800),
            hard_timeout_seconds=safe_int(self.hard_timeout_var.get(), 1800, 1, 7200),
            retry_count=safe_int(self.retry_count_var.get(), 0, 0, 5),
            retry_delay=safe_int(self.retry_delay_var.get(), 3, 0, 60),
        )

    def _validate_settings(self, settings: RequestSettings) -> Optional[str]:
        if not settings.base_url.startswith(("http://", "https://")):
            return "Base URL 必须以 http:// 或 https:// 开头。"
        if not settings.api_key:
            return "请填写 API Key。"
        if not settings.prompt:
            return "请填写提示词。"
        if settings.mode == "edit" and not settings.image_paths:
            return "图生图模式需要至少选择 1 张输入图片；文生图模式无需选择图片。"
        if is_grok_platform(settings.platform, settings.base_url) and settings.mode == "edit" and len(settings.image_paths) > 3:
            return "Grok/xAI 图生图最多建议选择 3 张输入图片。"
        if settings.image_count not in {1, 2, 3}:
            return "生成张数只能选择 1、2 或 3。"
        if settings.hard_timeout_seconds <= settings.background_after_seconds:
            return "后台最长等待必须大于后台等待阈值。"
        total = sum(Path(p).stat().st_size for p in settings.image_paths if Path(p).exists())
        if total > MAX_INPUT_BYTES:
            return f"输入图片总大小 {human_size(total)}，超过 30MB 限制。"
        if settings.size != "auto":
            try:
                w_text, h_text = settings.size.lower().split("x", 1)
                w, h = int(w_text), int(h_text)
                if w <= 0 or h <= 0 or w % 16 != 0 or h % 16 != 0:
                    return "自定义尺寸宽高必须为正数且为 16 的倍数。"
                if max(w, h) / min(w, h) > 3:
                    return "自定义尺寸宽高比例必须 <= 3:1。"
            except Exception:
                return "尺寸格式应为 auto 或 WIDTHxHEIGHT，例如 1024x1536。"
        return None

    def _start(self) -> None:
        if self.running:
            return
        settings = self._current_settings()
        err = self._validate_settings(settings)
        if err:
            messagebox.showerror("参数错误", err)
            return
        prompts = self._build_batch_prompts(settings.prompt)
        if not prompts:
            messagebox.showerror("参数错误", "请填写提示词。")
            return
        if self.prompt_mode_var.get() == "lines":
            self.total_requests_var.set(len(prompts))
        try:
            Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("输出目录错误", str(exc))
            return
        existing_background = self.background_wait_count
        self._record_started_prompt_history(prompts, settings.prompt)
        self.current_batch_id += 1
        batch_id = self.current_batch_id
        batch_stop_event = threading.Event()
        self.important_log_paths[batch_id] = self.important_log_path
        self.important_log_error_reported = False
        self._append_important_log(
            batch_id,
            f"START batch={batch_id} total={len(prompts)} output_dir={self._short_important_text(settings.output_dir)}",
        )
        self.stop_event = batch_stop_event
        self.running = True
        self.batch_stopping = False
        self.batch_prompt_for_history = prompts[0] if prompts else settings.prompt
        self.batch_history_recorded = False
        self.success_count = 0
        self.fail_count = 0
        self.completed_count = 0
        self.in_flight_count = 0
        self.total_elapsed = 0.0
        self.fastest_elapsed = None
        self.slowest_elapsed = None
        self.total_requests = len(prompts)
        concurrency = min(safe_int(self.concurrency_var.get(), 1, 1, 100), self.total_requests)
        self.batch_concurrency = max(1, concurrency)
        self.batch_timeout = max(1, settings.background_after_seconds)
        self.background_wait_limit = min(20, max(4, concurrency * 2))
        expected_images = self.total_requests * max(1, settings.image_count)
        self._init_request_statuses(self.total_requests, settings.retry_count)
        self.batch_started_at = time.time()
        self.progress_percent = 0
        self.progress_text = f"0/{self.total_requests} 0%"
        self.fake_progress = 0
        self.progress_animating = True
        self._draw_progress()
        self._update_stats()
        self._start_elapsed_timer()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        platform_name = platform_api_to_label(settings.platform)
        style_name = style_api_to_label(settings.style)
        self._enqueue_log(
            f"开始 | Images生成 | 平台:{platform_name} 总数:{self.total_requests} 并发:{concurrency} "
            f"单次张数:{settings.image_count} 预计生成:{expected_images} 张 "
            f"尺寸:{size_label(settings.size)} 质量:{settings.quality} "
            f"风格:{style_name} 格式:{settings.output_format} 模型:{settings.model} "
            f"\u91cd\u8bd5:{settings.retry_count} \u95f4\u9694:{settings.retry_delay}s \u540e\u53f0\u9608\u503c:{settings.background_after_seconds}s \u540e\u53f0\u6700\u957f:{settings.hard_timeout_seconds}s"
        )
        self._enqueue_log(f"\u91cd\u8981\u65e5\u5fd7: {self.important_log_paths[batch_id]}")
        if existing_background > 0:
            self._enqueue_log(f"已有 {existing_background} 个旧后台请求未返回；新批次照常开始，旧后台完成只自动保存并写日志，不计入本批统计。")
        if should_resize_output(settings):
            self._enqueue_log(f"已启用本地尺寸校正：服务商返回非目标尺寸时会保存后调整为 {settings.size}")
        if is_grok_platform(settings.platform, settings.base_url) and settings.mode == "generate" and settings.size != "auto":
            self._enqueue_log(
                f"Grok/xAI 参数映射: aspect_ratio={grok_size_to_aspect_ratio(settings.size)} "
                f"resolution={grok_size_to_resolution(settings.size) or 'auto'}"
            )
        self._enqueue_log(f"接口: {settings.base_url}/images/{'edits' if settings.mode == 'edit' else 'generations'}")
        self._animate_progress()
        self.worker_thread = threading.Thread(target=self._run_batch, args=(settings, prompts, concurrency, batch_id, batch_stop_event), daemon=True)
        self.worker_thread.start()

    def _build_batch_prompts(self, prompt: str) -> List[str]:
        if self.prompt_mode_var.get() == "lines":
            raw_prompts = [line.strip() for line in prompt.splitlines() if line.strip()]
        else:
            total = safe_int(self.total_requests_var.get(), 1, 1, 10000)
            raw_prompts = [prompt.strip()] * total
        return [item.replace("{index}", str(idx)) for idx, item in enumerate(raw_prompts, start=1)]

    def _stop(self) -> None:
        if self.running:
            self.batch_stopping = True
            self.stop_event.set()
            canceled = 0
            for idx, info in self.request_statuses.items():
                if info.get("status") == "等待中":
                    self._update_request_status(idx, status="已取消", result="未提交")
                    canceled += 1
            self._update_stop_waiting_status()
            self._enqueue_log(f"已请求停止：未开始请求已取消 {canceled} 个，已发出的请求会等待返回。")
            self.stop_button.configure(state="disabled")
            self._update_stats()
            self._set_real_progress()

    def _animate_progress(self) -> None:
        if not self.progress_animating or not self.running:
            return
        self.fake_progress = (self.fake_progress + 4) % 101
        self._draw_progress()
        self.after(60, self._animate_progress)

    def _set_real_progress(self) -> None:
        total = max(self.total_requests, 1)
        percent = int(max(0, min(100, self.completed_count * 100 / total)))
        self.progress_percent = percent
        if self.batch_stopping and self.running:
            self.progress_text = f"已停止 {self.completed_count}/{self.total_requests}"
        else:
            self.progress_text = f"{self.completed_count}/{self.total_requests} {percent}%"
        self._draw_progress()

    def _draw_progress(self) -> None:
        if self.progress_canvas is None:
            return
        canvas = self.progress_canvas
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#e6e6e6", outline="#b8b8b8")
        if self.progress_animating and self.running and self.in_flight_count > 0:
            segment_width = max(40, width // 5)
            travel_width = width + segment_width
            x1 = int((self.fake_progress / 100) * travel_width) - segment_width
            x2 = x1 + segment_width
            canvas.create_rectangle(max(0, x1), 1, min(width, x2), height - 1, fill="#2f80ed", outline="")
        real_width = int(width * self.progress_percent / 100)
        if real_width > 0:
            canvas.create_rectangle(0, 1, real_width, height - 1, fill="#08b937", outline="")
        canvas.create_text(width // 2, height // 2, text=self.progress_text, fill="#111111")

    def _init_request_statuses(self, total: int, max_retry: int) -> None:
        self.request_statuses = {}
        if self.status_tree is not None:
            for item in self.status_tree.get_children():
                self.status_tree.delete(item)
        for idx in range(1, total + 1):
            self.request_statuses[idx] = {
                "status": "等待中",
                "elapsed": "",
                "retry": f"0/{max_retry}",
                "result": "",
            }
            if self.status_tree is not None:
                self.status_tree.insert("", "end", iid=str(idx), values=(idx, "等待中", "", f"0/{max_retry}", ""))

    def _update_request_status(
        self,
        idx: int,
        status: Optional[str] = None,
        elapsed: Optional[float] = None,
        retry_used: Optional[int] = None,
        max_retry: Optional[int] = None,
        result: Optional[str] = None,
    ) -> None:
        info = self.request_statuses.setdefault(idx, {"status": "等待中", "elapsed": "", "retry": "", "result": ""})
        if status is not None:
            info["status"] = status
        if elapsed is not None:
            info["elapsed"] = f"{elapsed:.1f}s"
        if retry_used is not None:
            if max_retry is None:
                max_retry = safe_int(str(info.get("retry", "0/0")).split("/")[-1], 0, 0, 5)
            info["retry"] = f"{retry_used}/{max_retry}"
        if result is not None:
            info["result"] = self._short_result(result)
        if self.status_tree is not None:
            values = (idx, info.get("status", ""), info.get("elapsed", ""), info.get("retry", ""), info.get("result", ""))
            iid = str(idx)
            if self.status_tree.exists(iid):
                self.status_tree.item(iid, values=values)
            else:
                self.status_tree.insert("", "end", iid=iid, values=values)
            self.status_tree.see(iid)

    def _short_result(self, result: str, limit: int = 120) -> str:
        result = " ".join(str(result).split())
        return result if len(result) <= limit else result[: limit - 3] + "..."

    def _update_stop_waiting_status(self) -> None:
        if self.batch_stopping and self.running:
            self.elapsed_var.set(f"\u505c\u6b62\u4e2d\uff1a\u524d\u53f0 {self.in_flight_count}\uff0c\u540e\u53f0 {self.background_wait_count}")

    def _start_elapsed_timer(self) -> None:
        self.elapsed_timer_token += 1
        self.elapsed_timer_running = True
        self._update_elapsed_timer(self.elapsed_timer_token)

    def _stop_elapsed_timer(self) -> None:
        self.elapsed_timer_token += 1
        self.elapsed_timer_running = False

    def _update_elapsed_timer(self, token: Optional[int] = None) -> None:
        if token is None:
            token = self.elapsed_timer_token
        if token != self.elapsed_timer_token:
            return
        if self.batch_started_at is None:
            self.elapsed_var.set("\u8017\u65f6:0.0s")
            return
        elapsed = time.time() - self.batch_started_at
        if self.background_wait_count > 0 and not self.running:
            self.elapsed_var.set(f"\u540e\u53f0\u7b49\u5f85\u4e2d\uff1a{self.background_wait_count} \u4e2a\uff0c\u8017\u65f6:{elapsed:.1f}s")
        elif self.batch_stopping and self.running:
            self.elapsed_var.set(f"\u505c\u6b62\u4e2d\uff1a\u524d\u53f0 {self.in_flight_count}\uff0c\u540e\u53f0 {self.background_wait_count}")
        else:
            self.elapsed_var.set(f"\u8017\u65f6:{elapsed:.1f}s")
        if self.elapsed_timer_running:
            self.after(200, lambda token=token: self._update_elapsed_timer(token))

    def _run_batch(
        self,
        settings: RequestSettings,
        prompts: List[str],
        concurrency: int,
        batch_id: int,
        stop_event: threading.Event,
    ) -> None:
        started_at = time.time()
        total = len(prompts)
        next_index = 1
        futures: Dict[Any, int] = {}
        scheduler_executor = ThreadPoolExecutor(max_workers=concurrency)
        request_executor = ThreadPoolExecutor(max_workers=max(concurrency, self.background_wait_limit, 1))

        def submit_one(idx: int) -> None:
            prompt_settings = replace(settings, prompt=prompts[idx - 1])
            self.log_queue.put(("status", (batch_id, idx, "进行中", None, 0, settings.retry_count, "")))
            futures[scheduler_executor.submit(self._run_one_with_background, request_executor, prompt_settings, idx, batch_id, stop_event)] = idx

        try:
            while next_index <= total and len(futures) < concurrency and not stop_event.is_set():
                submit_one(next_index)
                next_index += 1
            while futures:
                done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                for fut in done:
                    idx = futures.pop(fut)
                    try:
                        ok, elapsed, msg, prompt, retry_used, status = fut.result()
                    except Exception as exc:
                        ok, elapsed, msg, prompt, retry_used, status = (
                            False,
                            0.0,
                            f"未捕获异常: {exc}\n{traceback.format_exc()}",
                            prompts[idx - 1] if idx - 1 < len(prompts) else settings.prompt,
                            0,
                            "失败",
                        )
                    self.log_queue.put(("result", (batch_id, idx, ok, elapsed, msg, prompt, retry_used, status)))
                while next_index <= total and len(futures) < concurrency and not stop_event.is_set():
                    submit_one(next_index)
                    next_index += 1
            if stop_event.is_set() and next_index <= total:
                for idx in range(next_index, total + 1):
                    self.log_queue.put(("status", (batch_id, idx, "已取消", None, None, settings.retry_count, "未提交")))
        finally:
            scheduler_executor.shutdown(wait=False, cancel_futures=True)
            request_executor.shutdown(wait=False, cancel_futures=False)
            self.log_queue.put(("done", (batch_id, time.time() - started_at)))

    def _run_one_with_background(
        self,
        request_executor: ThreadPoolExecutor,
        settings: RequestSettings,
        index: int,
        batch_id: int,
        stop_event: threading.Event,
    ) -> Tuple[bool, float, str, str, int, str]:
        request_future = request_executor.submit(self._run_one_request, settings, index, batch_id, stop_event)
        soft_timeout = max(1, settings.background_after_seconds)
        try:
            return request_future.result(timeout=soft_timeout)
        except FutureTimeoutError:
            if not self._try_enter_background(batch_id):
                self.log_queue.put(("log", f"[#{index}] 后台等待已满，继续占用前台槽等待返回"))
                return request_future.result()
            self.log_queue.put(("background", (batch_id, index, soft_timeout, settings.retry_count, "转入后台等待")))
            request_future.add_done_callback(lambda fut, idx=index, bid=batch_id: self._on_background_request_done(bid, idx, fut))
            return False, float(soft_timeout), "已转入后台等待，返回后会自动保存。", settings.prompt, 0, "后台等待"

    def _try_enter_background(self, batch_id: int) -> bool:
        with self.background_lock:
            if self.background_wait_count >= self.background_wait_limit:
                return False
            self.background_wait_count += 1
            self.background_wait_by_batch[batch_id] = self.background_wait_by_batch.get(batch_id, 0) + 1
            return True

    def _leave_background(self, batch_id: int) -> None:
        with self.background_lock:
            self.background_wait_count = max(0, self.background_wait_count - 1)
            batch_count = self.background_wait_by_batch.get(batch_id, 0)
            if batch_count <= 1:
                self.background_wait_by_batch.pop(batch_id, None)
            else:
                self.background_wait_by_batch[batch_id] = batch_count - 1

    def _background_count_for_batch(self, batch_id: Optional[int] = None) -> int:
        if batch_id is None:
            batch_id = self.current_batch_id
        with self.background_lock:
            return self.background_wait_by_batch.get(batch_id, 0)

    def _on_background_request_done(self, batch_id: int, index: int, fut: Any) -> None:
        self._leave_background(batch_id)
        try:
            ok, elapsed, msg, prompt, retry_used, status = fut.result()
        except Exception as exc:
            ok, elapsed, msg, prompt, retry_used, status = (
                False,
                0.0,
                f"后台未捕获异常: {exc}\n{traceback.format_exc()}",
                "",
                0,
                "失败",
            )
        self.log_queue.put(("background_result", (batch_id, index, ok, elapsed, msg, prompt, retry_used, status)))

    def _run_one_request(
        self,
        settings: RequestSettings,
        index: int,
        batch_id: int,
        stop_event: threading.Event,
    ) -> Tuple[bool, float, str, str, int, str]:
        if stop_event.is_set():
            raise StopRequested("stop requested")
        started = time.time()
        retry_used = 0
        last_message = ""
        last_status = "失败"
        for attempt in range(settings.retry_count + 1):
            if stop_event.is_set() and attempt > 0:
                break
            attempt_started = time.time()
            client = ImageApiClient(settings.base_url, settings.api_key, timeout=settings.hard_timeout_seconds)
            try:
                if settings.mode == "generate":
                    response = client.generate(self._build_generation_payload(settings))
                elif is_grok_platform(settings.platform, settings.base_url):
                    response = client.edit_json(self._build_grok_edit_payload(settings))
                else:
                    response = client.edit(self._build_edit_fields(settings), settings.image_paths)
                saved_files = self._save_response_images(response, settings, index)
                elapsed = time.time() - started
                if saved_files:
                    return True, elapsed, "保存: " + "; ".join(saved_files), settings.prompt, retry_used, "成功"
                data = response.get("data") if isinstance(response, dict) else None
                if isinstance(data, list) and not data:
                    last_message = f"\u670d\u52a1\u5546\u54cd\u5e94 data \u4e3a\u7a7a\uff1b\u5e73\u53f0\u4fa7\u5b8c\u6210/\u8ba1\u8d39\u4e0d\u4ee3\u8868\u54cd\u5e94\u91cc\u5305\u542b\u56fe\u7247\uff0c\u672c\u5730\u672a\u6536\u5230 b64_json \u6216 url\uff0c\u65e0\u6cd5\u4fdd\u5b58: {compact_json(response)}"
                else:
                    last_message = f"\u54cd\u5e94\u4e2d\u672a\u627e\u5230 b64_json \u6216 url: {compact_json(response)}"
                last_status = "失败"
            except Exception as exc:
                last_message = str(exc)
                last_status = "超时" if self._is_timeout_error(exc) else "失败"
            if attempt < settings.retry_count and self._should_retry_error(last_message):
                retry_used = attempt + 1
                self.log_queue.put(("retry", (batch_id, index, retry_used, settings.retry_count, last_message)))
                if settings.retry_delay > 0:
                    time.sleep(settings.retry_delay)
                continue
            break
        return False, time.time() - started, last_message, settings.prompt, retry_used, last_status

    def _is_timeout_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "超时" in str(exc) or "timed out" in text or "timeout" in text or isinstance(exc, (TimeoutError, socket.timeout))

    def _should_retry_error(self, message: str) -> bool:
        lower = message.lower()
        retry_markers = ["网络超时", "timed out", "timeout", "connection reset", "temporarily", "网络错误"]
        if any(marker in lower for marker in retry_markers):
            return True
        for code in (429, 500, 502, 503, 504):
            if f"http {code}" in lower:
                return True
        for code in (400, 401, 403, 404):
            if f"http {code}" in lower:
                return False
        return False

    def _build_generation_payload(self, settings: RequestSettings) -> Dict[str, Any]:
        if is_grok_platform(settings.platform, settings.base_url):
            payload: Dict[str, Any] = {
                "model": settings.model,
                "prompt": settings.prompt,
                "n": settings.image_count,
                "response_format": "b64_json",
            }
            aspect_ratio = grok_size_to_aspect_ratio(settings.size)
            resolution = grok_size_to_resolution(settings.size)
            if aspect_ratio:
                payload["aspect_ratio"] = aspect_ratio
            if resolution:
                payload["resolution"] = resolution
            return payload

        payload = {
            "model": settings.model,
            "prompt": settings.prompt,
            "n": settings.image_count,
            "size": settings.size,
        }
        if settings.quality:
            payload["quality"] = settings.quality
        if settings.style:
            payload["style"] = settings.style
        if settings.output_format:
            payload["output_format"] = settings.output_format
        if settings.output_format in {"jpeg", "webp"}:
            payload["output_compression"] = settings.compression
        return payload

    def _build_edit_fields(self, settings: RequestSettings) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            "model": settings.model,
            "prompt": settings.prompt,
            "n": settings.image_count,
            "size": settings.size,
        }
        if is_grok_platform(settings.platform, settings.base_url):
            fields["response_format"] = "b64_json"
            aspect_ratio = grok_size_to_aspect_ratio(settings.size)
            resolution = grok_size_to_resolution(settings.size)
            if aspect_ratio:
                fields["aspect_ratio"] = aspect_ratio
            if resolution:
                fields["resolution"] = resolution
        if settings.quality:
            fields["quality"] = settings.quality
        if settings.style:
            fields["style"] = settings.style
        if settings.output_format:
            fields["output_format"] = settings.output_format
        if settings.output_format in {"jpeg", "webp"}:
            fields["output_compression"] = settings.compression
        return fields

    def _build_grok_edit_payload(self, settings: RequestSettings) -> Dict[str, Any]:
        image_urls = [image_file_to_data_url(path) for path in settings.image_paths]
        payload: Dict[str, Any] = {
            "model": settings.model,
            "prompt": settings.prompt,
            "n": settings.image_count,
        }
        if len(image_urls) == 1:
            payload["image"] = {"type": "image_url", "url": image_urls[0]}
        else:
            payload["images"] = [{"type": "image_url", "url": url} for url in image_urls[:3]]
            aspect_ratio = grok_size_to_aspect_ratio(settings.size)
            if aspect_ratio:
                payload["aspect_ratio"] = aspect_ratio
        return payload

    def _save_response_images(self, response: Dict[str, Any], settings: RequestSettings, index: int) -> List[str]:
        data = response.get("data")
        if not isinstance(data, list):
            return []
        out_dir = Path(settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: List[str] = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        extension = "jpg" if settings.output_format == "jpeg" else (settings.output_format or "png")
        for image_idx, item in enumerate(data, start=1):
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json")
            if b64:
                file_path = out_dir / f"{timestamp}_req{index:04d}_{image_idx}.{extension}"
                self._atomic_write_bytes(file_path, base64.b64decode(b64))
                self._resize_saved_image_if_needed(file_path, settings)
                saved.append(str(file_path))
                continue
            url = item.get("url")
            if url:
                file_path = out_dir / f"{timestamp}_req{index:04d}_{image_idx}.{extension}"
                self._download_image(url, file_path, settings.api_key, settings.hard_timeout_seconds)
                self._resize_saved_image_if_needed(file_path, settings)
                saved.append(str(file_path))
        return saved

    def _atomic_write_bytes(self, out_path: Path, data: bytes) -> None:
        tmp_path = out_path.with_name(f"{out_path.name}.{uuid4().hex}.tmp")
        try:
            tmp_path.write_bytes(data)
            os.replace(str(tmp_path), str(out_path))
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

    def _resize_saved_image_if_needed(self, file_path: Path, settings: RequestSettings) -> None:
        if not should_resize_output(settings) or Image is None:
            return
        try:
            w_text, h_text = settings.size.lower().split("x", 1)
            target = (int(w_text), int(h_text))
        except Exception:
            return
        try:
            with Image.open(file_path) as img:  # type: ignore[union-attr]
                if img.size == target:
                    return
                resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)  # type: ignore[union-attr]
                resized = self._cover_resize(img, target, resample)
                save_kwargs: Dict[str, Any] = {}
                if settings.output_format == "jpeg":
                    if resized.mode in {"RGBA", "LA", "P"}:
                        resized = resized.convert("RGB")
                    save_kwargs["quality"] = settings.compression
                elif settings.output_format == "webp":
                    save_kwargs["quality"] = settings.compression
                resized.save(file_path, **save_kwargs)
        except Exception as exc:
            self.log_queue.put(("log", f"尺寸校正失败 {file_path.name}: {exc}"))

    def _cover_resize(self, img: Any, target: Tuple[int, int], resample: Any) -> Any:
        target_w, target_h = target
        src_w, src_h = img.size
        scale = max(target_w / src_w, target_h / src_h)
        new_size = (max(1, math.ceil(src_w * scale)), max(1, math.ceil(src_h * scale)))
        resized = img.resize(new_size, resample)
        left = max(0, (new_size[0] - target_w) // 2)
        top = max(0, (new_size[1] - target_h) // 2)
        return resized.crop((left, top, left + target_w, top + target_h))

    def _download_image(self, url: str, out_path: Path, api_key: str, timeout: int) -> None:
        headers = {"User-Agent": "GPTImageGeneratorStressPanel/1.0"}
        if urllib.parse.urlparse(url).netloc == urllib.parse.urlparse(normalize_base_url(self.base_url_var.get())).netloc:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                self._atomic_write_bytes(out_path, resp.read())
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                raise ImageApiError(f"下载超时（超过 {timeout}s）") from exc
            raise ImageApiError(f"下载失败: {reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise ImageApiError(f"下载超时（超过 {timeout}s）") from exc

    def _enqueue_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _on_close(self) -> None:
        if self.background_wait_count > 0 and not self.closed_forcefully:
            keep_waiting = messagebox.askyesno(
                "后台请求仍在等待",
                f"还有 {self.background_wait_count} 个后台请求未返回。\n\n"
                "选择“是”继续等待；选择“否”强制退出（可能无法保存这些请求返回的图片）。",
            )
            if keep_waiting:
                return
            self.closed_forcefully = True
        self.destroy()
        if self.closed_forcefully:
            os._exit(0)

    def _poll_log_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "status":
                    batch_id, idx, status, elapsed, retry_used, max_retry, result = payload
                    if batch_id != self.current_batch_id:
                        continue
                    old_status = self.request_statuses.get(idx, {}).get("status")
                    if old_status != "进行中" and status == "进行中":
                        self.in_flight_count += 1
                    self._update_request_status(idx, status=status, elapsed=elapsed, retry_used=retry_used, max_retry=max_retry, result=result)
                    self._update_stats()
                    self._draw_progress()
                    self._update_stop_waiting_status()
                elif kind == "retry":
                    batch_id, idx, retry_used, max_retry, reason = payload
                    if batch_id != self.current_batch_id:
                        self._append_log(f"[批次{batch_id} #{idx}] 旧批次第 {retry_used}/{max_retry} 次重试，原因: {reason}")
                        continue
                    self._update_request_status(idx, status="进行中", retry_used=retry_used, max_retry=max_retry, result=f"重试中: {reason}")
                    self._append_log(f"[#{idx}] 第 {retry_used}/{max_retry} 次重试，原因: {reason}")
                elif kind == "background":
                    batch_id, idx, elapsed, max_retry, result = payload
                    if batch_id != self.current_batch_id:
                        self._append_log(f"[批次{batch_id} #{idx}] 旧批次转入后台等待 {elapsed:.1f}s | 返回后自动保存")
                        self._update_stats()
                        continue
                    self.in_flight_count = max(0, self.in_flight_count - 1)
                    self._update_request_status(idx, status="\u540e\u53f0\u7b49\u5f85", elapsed=elapsed, retry_used=0, max_retry=max_retry, result=result)
                    self._append_log(f"[#{idx}] \u8f6c\u5165\u540e\u53f0\u7b49\u5f85 {elapsed:.1f}s | \u8fd4\u56de\u540e\u81ea\u52a8\u4fdd\u5b58")
                    self._set_real_progress()
                    self._update_stats()
                    self._update_stop_waiting_status()
                elif kind == "result":
                    batch_id, idx, ok, elapsed, msg, prompt, retry_used, status = payload
                    if batch_id != self.current_batch_id:
                        if status != "\u540e\u53f0\u7b49\u5f85":
                            final_status = "\u6210\u529f" if ok else self._normalize_final_status(status)
                            self._append_important_result(batch_id, idx, final_status, elapsed, msg, retry_used, "\u524d\u53f0\u5b8c\u6210")
                            self._append_log(f"[批次{batch_id} #{idx}] 旧批次前台完成 {final_status} {elapsed:.1f}s | {msg}")
                        continue
                    if status == "\u540e\u53f0\u7b49\u5f85":
                        self._update_request_status(idx, status="\u540e\u53f0\u7b49\u5f85", elapsed=elapsed, retry_used=retry_used, max_retry=None, result=msg)
                    else:
                        self.in_flight_count = max(0, self.in_flight_count - 1)
                        self._apply_final_result(idx, ok, elapsed, msg, prompt, retry_used, status, "\u524d\u53f0\u5b8c\u6210", batch_id)
                elif kind == "background_result":
                    batch_id, idx, ok, elapsed, msg, prompt, retry_used, status = payload
                    if batch_id != self.current_batch_id:
                        final_status = "\u6210\u529f" if ok else self._normalize_final_status(status)
                        self._append_important_result(batch_id, idx, final_status, elapsed, msg, retry_used, "\u540e\u53f0\u5b8c\u6210")
                        self._append_log(f"[批次{batch_id} #{idx}] 旧批次后台完成 {final_status} {elapsed:.1f}s | {msg}")
                        if not self.running and self.background_wait_count == 0:
                            self._stop_elapsed_timer()
                        self._update_stats()
                        continue
                    self._apply_final_result(idx, ok, elapsed, msg, prompt, retry_used, status, "\u540e\u53f0\u5b8c\u6210", batch_id)
                elif kind == "done":
                    batch_id, elapsed_total = payload
                    elapsed_total = float(elapsed_total)
                    if batch_id != self.current_batch_id:
                        self._append_log(f"旧批次前台完成 | 批次:{batch_id} 后台等待:{self._background_count_for_batch(batch_id)} 耗时:{elapsed_total:.1f}s")
                        self._update_stats()
                        continue
                    current_background = self._background_count_for_batch(batch_id)
                    self.progress_animating = False
                    self.in_flight_count = 0
                    if self.background_wait_count > 0:
                        self.elapsed_timer_running = True
                    else:
                        self._stop_elapsed_timer()
                    if self.batch_stopping and self.completed_count < self.total_requests:
                        self.progress_text = f"已停止 {self.completed_count}/{self.total_requests}"
                    else:
                        self._set_real_progress()
                        if self.completed_count >= self.total_requests:
                            self.progress_percent = 100
                            self.progress_text = f"{self.total_requests}/{self.total_requests} 100%"
                    self._draw_progress()
                    if current_background > 0:
                        self.elapsed_var.set(f"\u524d\u53f0\u5b8c\u6210:{elapsed_total:.1f}s\uff0c\u540e\u53f0\u7b49\u5f85:{current_background}")
                    else:
                        self.elapsed_var.set(f"\u8017\u65f6:{elapsed_total:.1f}s")
                    self._append_log(
                        f"\u524d\u53f0\u5b8c\u6210 | \u6210\u529f:{self.success_count} \u5931\u8d25:{self.fail_count}/{self.total_requests} "
                        f"\u672c\u6279\u540e\u53f0\u7b49\u5f85:{current_background} \u540e\u53f0\u603b\u6570:{self.background_wait_count} \u8017\u65f6:{elapsed_total:.1f}s"
                    )
                    self._append_important_summary(batch_id, elapsed_total, current_background, "\u524d\u53f0\u5b8c\u6210")
                    self.running = False
                    self.batch_stopping = False
                    self.batch_prompt_for_history = ""
                    self.batch_history_recorded = False
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self._update_stats()
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _normalize_final_status(self, status: str) -> str:
        status_text = str(status or "").lower()
        if "timeout" in status_text or "timed out" in status_text or "\u8d85\u65f6" in str(status):
            return "\u8d85\u65f6"
        if status_text in {"success", "ok", "done"} or "\u6210\u529f" in str(status):
            return "\u6210\u529f"
        return "\u5931\u8d25"

    def _apply_final_result(
        self,
        idx: int,
        ok: bool,
        elapsed: float,
        msg: str,
        prompt: str,
        retry_used: int,
        status: str,
        source: str,
        batch_id: Optional[int] = None,
    ) -> None:
        old_status = self.request_statuses.get(idx, {}).get("status")
        if old_status in {"\u6210\u529f", "\u5931\u8d25", "\u8d85\u65f6", "\u5b8c\u6210"}:
            self._update_request_status(idx, result=msg)
            return
        self.completed_count += 1
        self.total_elapsed += elapsed
        self.fastest_elapsed = elapsed if self.fastest_elapsed is None else min(self.fastest_elapsed, elapsed)
        self.slowest_elapsed = elapsed if self.slowest_elapsed is None else max(self.slowest_elapsed, elapsed)
        if ok:
            self.success_count += 1
            final_status = "\u6210\u529f"
            self._append_log(f"[#{idx}] {source} \u6210\u529f {elapsed:.1f}s | {msg}")
        else:
            self.fail_count += 1
            final_status = self._normalize_final_status(status)
            self._append_log(f"[#{idx}] {source} {final_status} {elapsed:.1f}s | {msg}")
        self._append_important_result(batch_id, idx, final_status, elapsed, msg, retry_used, source)
        max_retry = safe_int(str(self.request_statuses.get(idx, {}).get("retry", "0/0")).split("/")[-1], 0, 0, 5)
        self._update_request_status(idx, status=final_status, elapsed=elapsed, retry_used=retry_used, max_retry=max_retry, result=msg)
        self._set_real_progress()
        current_background = self._background_count_for_batch(batch_id)
        if not self.running and current_background == 0:
            self._stop_elapsed_timer()
            if self.completed_count >= self.total_requests:
                self.progress_percent = 100
                self.progress_text = f"{self.total_requests}/{self.total_requests} 100%"
                self._draw_progress()
                self.elapsed_var.set(f"\u5b8c\u6210\uff1a\u6210\u529f {self.success_count}\uff0c\u5931\u8d25 {self.fail_count}")
                self._append_log(f"\u5168\u90e8\u5b8c\u6210 | \u6210\u529f:{self.success_count} \u5931\u8d25:{self.fail_count}/{self.total_requests}")
                self._append_important_summary(batch_id, self.total_elapsed, 0, "\u5168\u90e8\u5b8c\u6210")
            self.batch_prompt_for_history = ""
            self.batch_history_recorded = False
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        self._update_stats()
        self._update_stop_waiting_status()

    def _short_important_text(self, value: Any, limit: int = 500) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[: limit - 3] + "..."

    def _append_important_log(self, batch_id: Optional[int], message: str) -> None:
        if batch_id is None:
            batch_id = self.current_batch_id
        log_path = self.important_log_paths.get(batch_id)
        if log_path is None:
            try:
                log_path = self.important_log_path
            except Exception:
                return
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{timestamp}] {message}\n")
        except Exception as exc:
            if not self.important_log_error_reported:
                self.important_log_error_reported = True
                self._append_log(f"\u91cd\u8981\u65e5\u5fd7\u4fdd\u5b58\u5931\u8d25: {exc}")

    def _append_important_result(
        self,
        batch_id: Optional[int],
        idx: int,
        final_status: str,
        elapsed: float,
        msg: str,
        retry_used: int,
        source: str,
    ) -> None:
        status = self._short_important_text(final_status, 30)
        source_text = self._short_important_text(source, 30)
        message = self._short_important_text(msg)
        self._append_important_log(
            batch_id,
            f"RESULT batch={batch_id} request={idx} source={source_text} status={status} "
            f"elapsed={elapsed:.1f}s retry={retry_used} message={message}",
        )

    def _append_important_summary(
        self,
        batch_id: Optional[int],
        elapsed_total: float,
        background_wait: int,
        source: str,
    ) -> None:
        source_text = self._short_important_text(source, 30)
        self._append_important_log(
            batch_id,
            f"SUMMARY batch={batch_id} source={source_text} success={self.success_count} "
            f"fail={self.fail_count} total={self.total_requests} background_wait={background_wait} "
            f"elapsed={elapsed_total:.1f}s",
        )

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_stats(self) -> None:
        avg = self.total_elapsed / self.completed_count if self.completed_count else 0.0
        success_rate = (self.success_count * 100 / self.completed_count) if self.completed_count else 0.0
        fastest = f"{self.fastest_elapsed:.1f}s" if self.fastest_elapsed is not None else "--"
        slowest = f"{self.slowest_elapsed:.1f}s" if self.slowest_elapsed is not None else "--"
        remaining = max(self.total_requests - self.completed_count, 0)
        if remaining == 0 and self.total_requests:
            eta = "0.0s"
        elif self.running:
            unit_seconds = avg if self.completed_count else float(self.batch_timeout)
            waves = max(1, math.ceil(remaining / max(1, self.batch_concurrency)))
            eta_seconds = waves * unit_seconds
            if not self.completed_count and self.batch_started_at is not None:
                eta_seconds = max(0.0, eta_seconds - (time.time() - self.batch_started_at))
            eta = f"{eta_seconds:.1f}s"
        else:
            eta = "--"
        self.stats_vars["success"].set(f"\u6210\u529f:{self.success_count}")
        self.stats_vars["fail"].set(f"\u5931\u8d25:{self.fail_count}")
        self.stats_vars["running"].set(f"\u8fdb\u884c\u4e2d:{self.in_flight_count}")
        self.stats_vars["background"].set(f"\u540e\u53f0:{self.background_wait_count}")
        self.stats_vars["rate"].set(f"\u6210\u529f\u7387:{success_rate:.0f}%")
        self.stats_vars["avg"].set(f"\u5e73\u5747:{avg:.1f}s")
        self.stats_vars["fastest"].set(f"\u6700\u5feb:{fastest}")
        self.stats_vars["slowest"].set(f"\u6700\u6162:{slowest}")
        self.stats_vars["eta"].set(f"\u9884\u8ba1\u5269\u4f59:{eta}")


def main() -> None:
    root = GPTImageApp()
    try:
        from tkinter import font as tkfont
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family="Microsoft YaHei UI", size=9)
            except Exception:
                pass
        root.option_add("*Font", "{Microsoft YaHei UI} 9")
    except Exception:
        pass
    root.mainloop()


if __name__ == "__main__":
    main()
