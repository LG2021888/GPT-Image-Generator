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
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
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
DEFAULT_GROK_MODEL = "grok-imagine-image-quality"
CONFIG_FILE = "config.ini"
DEFAULT_PROFILE = "默认"
PROMPT_HISTORY_LIMIT = 30

PRESET_SIZES = [
    "自动（模型自动选择）",
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
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
            raise ImageApiError(f"网络错误: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ImageApiError("网络超时") from exc


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


class GPTImageApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x780")
        self.minsize(920, 680)

        self.config_path = app_base_dir() / CONFIG_FILE
        self.log_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.profiles: Dict[str, Dict[str, str]] = {}
        self.prompt_history: List[str] = []
        self.prompt_history_popup: Optional[tk.Toplevel] = None
        self.selected_images: List[str] = []
        self.running = False
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.progress_animating = False
        self.fake_progress = 0
        self.batch_started_at: Optional[float] = None
        self.elapsed_timer_running = False
        self.batch_prompt_for_history = ""
        self.batch_history_recorded = False
        self.success_count = 0
        self.fail_count = 0
        self.completed_count = 0
        self.total_elapsed = 0.0
        self.total_requests = 1

        self._init_vars()
        self._build_ui()
        self._load_config()
        self._on_mode_change()
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
        default_output = str((Path.cwd() / "output").resolve())
        self.output_dir_var = tk.StringVar(value=default_output)
        self.stats_var = tk.StringVar(value="成功:0 失败:0 平均:0.0s")
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

    def _build_api_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="API 配置", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
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
        self.prompt_text = tk.Text(frame, height=3, wrap="word", undo=True)
        self.prompt_text.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.prompt_history_button = ttk.Button(frame, text="历史", width=8, command=self._show_prompt_history)
        self.prompt_history_button.grid(row=0, column=1, sticky="ns")
        self.prompt_text.insert("1.0", "输入你的图片生成提示词；图生图模式下会结合所选图片进行编辑或参考。")

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

    def _build_control_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(frame, text="开始生成", command=self._start)
        self.start_button.grid(row=0, column=0, sticky="w")
        self.stop_button = ttk.Button(frame, text="停止", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(12, 18))
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100, value=0)
        self.progress.grid(row=0, column=2, sticky="ew", padx=(0, 12))
        ttk.Label(frame, textvariable=self.elapsed_var).grid(row=0, column=3, sticky="e", padx=(0, 12))
        ttk.Label(frame, textvariable=self.stats_var).grid(row=0, column=4, sticky="e")

    def _build_log_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="日志", padding=6)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(frame, height=10, wrap="word", state="disabled")
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
        if self.prompt_history_popup is not None and self.prompt_history_popup.winfo_exists():
            self.prompt_history_popup.lift()
            self.prompt_history_popup.focus_force()
            return

        popup = tk.Toplevel(self)
        self.prompt_history_popup = popup
        popup.title("提示词历史")
        popup.transient(self)
        popup.attributes("-topmost", True)

        self.prompt_history_button.update_idletasks()
        width = 520
        height = 360
        x = self.prompt_history_button.winfo_rootx() + self.prompt_history_button.winfo_width() - width
        y = self.prompt_history_button.winfo_rooty() + self.prompt_history_button.winfo_height()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(0, min(x, screen_width - width))
        if y + height > screen_height:
            y = max(0, self.prompt_history_button.winfo_rooty() - height)
        popup.geometry(f"{width}x{height}+{x}+{y}")

        frame = ttk.Frame(popup, padding=6)
        frame.grid(row=0, column=0, sticky="nsew")
        popup.columnconfigure(0, weight=1)
        popup.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        def close(_event: Optional[tk.Event] = None) -> str:
            self._close_prompt_history_popup()
            return "break"

        def close_on_outside_click(event: tk.Event) -> Optional[str]:
            if not point_in_widget(popup, event.x_root, event.y_root):
                self._close_prompt_history_popup()
                return "break"
            return None

        if not self.prompt_history:
            ttk.Label(frame, text="暂无提示词历史").grid(row=0, column=0, sticky="nsew")
            popup.bind("<ButtonPress-1>", close_on_outside_click, add="+")
            popup.bind("<Escape>", close)
            popup.protocol("WM_DELETE_WINDOW", self._close_prompt_history_popup)
            popup.grab_set()
            popup.focus_force()
            return

        listbox = tk.Listbox(frame, height=min(len(self.prompt_history), 12), activestyle="dotbox")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        listbox.configure(yscrollcommand=scroll.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        for prompt in self.prompt_history:
            listbox.insert("end", self._prompt_history_preview(prompt))

        def choose(_event: Optional[tk.Event] = None) -> str:
            selection = listbox.curselection()
            if not selection:
                return "break"
            self._apply_prompt_history(int(selection[0]))
            return "break"

        listbox.bind("<ButtonRelease-1>", choose)
        listbox.bind("<Return>", choose)
        listbox.bind("<Escape>", close)
        popup.bind("<ButtonPress-1>", close_on_outside_click, add="+")
        popup.bind("<Escape>", close)
        popup.protocol("WM_DELETE_WINDOW", self._close_prompt_history_popup)
        popup.grab_set()
        popup.focus_force()
        listbox.focus_set()

    def _close_prompt_history_popup(self) -> None:
        popup = self.prompt_history_popup
        if popup is not None:
            try:
                if popup.winfo_exists():
                    if popup.grab_current() == popup:
                        popup.grab_release()
                    popup.destroy()
            except Exception:
                pass
        self.prompt_history_popup = None

    def _prompt_history_preview(self, prompt: str) -> str:
        preview = " ".join(prompt.split())
        if len(preview) > 96:
            return preview[:93] + "..."
        return preview

    def _apply_prompt_history(self, index: int) -> None:
        if index < 0 or index >= len(self.prompt_history):
            return
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", self.prompt_history[index])
        self.prompt_text.focus_set()
        self._close_prompt_history_popup()

    def _record_prompt_history(self, prompt: str) -> None:
        prompt = prompt.strip()
        if not prompt:
            return
        self.prompt_history = [item for item in self.prompt_history if item != prompt]
        self.prompt_history.insert(0, prompt)
        self.prompt_history = self.prompt_history[:PROMPT_HISTORY_LIMIT]
        try:
            self._write_config()
        except Exception as exc:
            self._enqueue_log(f"保存提示词历史失败: {exc}")

    def _load_config(self) -> None:
        cfg = configparser.ConfigParser()
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

        self.output_dir_var.set(app_sec.get("output_dir", self.output_dir_var.get()))
        saved_size = app_sec.get("size_preset", PRESET_SIZES[0])
        self.size_preset_var.set(PRESET_SIZES[0] if saved_size.startswith(("auto", "自动")) else saved_size)
        self.custom_size_var.set(app_sec.get("custom_size", ""))
        self.quality_var.set(quality_api_to_label(app_sec.get("quality", "high")))
        self.style_var.set(style_api_to_label(app_sec.get("style", "")))
        self.image_count_var.set(str(safe_int(app_sec.get("image_count", 1), 1, 1, 3)))
        self.format_var.set(app_sec.get("output_format", "jpeg"))
        self.compression_var.set(safe_int(app_sec.get("compression", 100), 100, 0, 100))
        self.mode_var.set(app_sec.get("mode", "edit"))
        self.prompt_history = self._load_prompt_history(cfg)

        self._refresh_profile_menu(current)
        self._apply_profile(current)
        if loaded:
            self._enqueue_log(f"已从 {self.config_path.name} 加载配置（当前 API 配置: {current}）")
        else:
            self._enqueue_log("未找到 config.ini，已使用默认配置")

    def _load_prompt_history(self, cfg: configparser.ConfigParser) -> List[str]:
        if not cfg.has_section("prompt_history"):
            return []
        raw = cfg.get("prompt_history", "items", fallback="[]").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception as exc:
            self._enqueue_log(f"提示词历史格式无效，已忽略: {exc}")
            return []
        if not isinstance(data, list):
            self._enqueue_log("提示词历史格式无效，已忽略: items 不是数组")
            return []

        history: List[str] = []
        ignored = 0
        for item in data:
            if not isinstance(item, str):
                ignored += 1
                continue
            prompt = item.strip()
            if not prompt:
                ignored += 1
                continue
            if prompt in history:
                continue
            history.append(prompt)
            if len(history) >= PROMPT_HISTORY_LIMIT:
                break
        if ignored:
            self._enqueue_log(f"提示词历史中有 {ignored} 条无效记录，已忽略")
        return history

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
        cfg = configparser.ConfigParser()
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
        }
        if not self.profiles:
            self.profiles[DEFAULT_PROFILE] = {
                "platform": platform_label_to_api(self.platform_var.get()),
                "base_url": normalize_base_url(self.base_url_var.get()),
                "api_key": self.api_key_var.get().strip(),
                "model": self.model_var.get().strip() or DEFAULT_MODEL,
            }
        cfg["prompt_history"] = {
            "items": json.dumps(self.prompt_history[:PROMPT_HISTORY_LIMIT], ensure_ascii=False),
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
        path = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir_var.get() or str(Path.cwd()))
        if path:
            self.output_dir_var.set(path)

    def _open_output_dir(self) -> None:
        path = Path(self.output_dir_var.get().strip() or (Path.cwd() / "output")).resolve()
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
        return RequestSettings(
            platform=platform,
            base_url=normalize_base_url(self.base_url_var.get()),
            api_key=self.api_key_var.get().strip(),
            mode=mode,
            image_paths=[] if mode == "generate" else list(self.selected_images),
            prompt=self.prompt_text.get("1.0", "end").strip(),
            size=size,
            image_count=safe_int(self.image_count_var.get(), 1, 1, 3),
            quality=quality_label_to_api(self.quality_var.get()),
            style=style_label_to_api(self.style_var.get()),
            output_format=self.format_var.get().strip() or "png",
            compression=safe_int(self.compression_var.get(), 100, 0, 100),
            model=self.model_var.get().strip() or DEFAULT_MODEL,
            output_dir=self.output_dir_var.get().strip() or str((Path.cwd() / "output").resolve()),
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
        try:
            Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("输出目录错误", str(exc))
            return
        self.running = True
        self.stop_event.clear()
        self.batch_prompt_for_history = settings.prompt
        self.batch_history_recorded = False
        self.success_count = 0
        self.fail_count = 0
        self.completed_count = 0
        self.total_elapsed = 0.0
        self.total_requests = safe_int(self.total_requests_var.get(), 1, 1, 10000)
        concurrency = min(safe_int(self.concurrency_var.get(), 1, 1, 100), self.total_requests)
        self.batch_started_at = time.time()
        self.elapsed_timer_running = True
        self.progress.configure(maximum=100, value=0)
        self.fake_progress = 0
        self.progress_animating = True
        self._update_stats()
        self._update_elapsed_timer()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        platform_name = platform_api_to_label(settings.platform)
        style_name = style_api_to_label(settings.style)
        self._enqueue_log(
            f"开始 | Images API 测试 | 平台:{platform_name} 总数:{self.total_requests} 并发:{concurrency} "
            f"单次张数:{settings.image_count} 尺寸:{size_label(settings.size)} 质量:{settings.quality} "
            f"风格:{style_name} 格式:{settings.output_format} 模型:{settings.model}"
        )
        if should_resize_output(settings):
            self._enqueue_log(f"已启用本地尺寸校正：服务商返回非目标尺寸时会保存后调整为 {settings.size}")
        if is_grok_platform(settings.platform, settings.base_url) and settings.mode == "generate" and settings.size != "auto":
            self._enqueue_log(
                f"Grok/xAI 参数映射: aspect_ratio={grok_size_to_aspect_ratio(settings.size)} "
                f"resolution={grok_size_to_resolution(settings.size) or 'auto'}"
            )
        self._enqueue_log(f"接口: {settings.base_url}/images/{'edits' if settings.mode == 'edit' else 'generations'}")
        self._animate_progress()
        self.worker_thread = threading.Thread(target=self._run_batch, args=(settings, self.total_requests, concurrency), daemon=True)
        self.worker_thread.start()

    def _stop(self) -> None:
        if self.running:
            self.stop_event.set()
            self._enqueue_log("已请求停止：未开始的请求将不再提交，已发出的请求会等待返回。")
            self.stop_button.configure(state="disabled")

    def _animate_progress(self) -> None:
        if not self.progress_animating or not self.running:
            return
        if self.completed_count > 0:
            self.progress_animating = False
            self._set_real_progress()
            return
        self.fake_progress = (self.fake_progress + 4) % 101
        self.progress.configure(value=self.fake_progress)
        self.after(60, self._animate_progress)

    def _set_real_progress(self) -> None:
        total = max(self.total_requests, 1)
        percent = int(max(0, min(100, self.completed_count * 100 / total)))
        self.progress.configure(value=percent)

    def _update_elapsed_timer(self) -> None:
        if self.batch_started_at is None:
            self.elapsed_var.set("耗时:0.0s")
            return
        elapsed = time.time() - self.batch_started_at
        self.elapsed_var.set(f"耗时:{elapsed:.1f}s")
        if self.elapsed_timer_running:
            self.after(200, self._update_elapsed_timer)

    def _run_batch(self, settings: RequestSettings, total: int, concurrency: int) -> None:
        started_at = time.time()
        next_index = 1
        futures: Dict[Any, int] = {}
        executor = ThreadPoolExecutor(max_workers=concurrency)
        try:
            while next_index <= total and len(futures) < concurrency and not self.stop_event.is_set():
                futures[executor.submit(self._run_one_request, settings, next_index)] = next_index
                next_index += 1
            while futures:
                done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                for fut in done:
                    idx = futures.pop(fut)
                    try:
                        ok, elapsed, msg = fut.result()
                    except Exception as exc:
                        ok, elapsed, msg = False, 0.0, f"未捕获异常: {exc}\n{traceback.format_exc()}"
                    self.log_queue.put(("result", (idx, ok, elapsed, msg)))
                while next_index <= total and len(futures) < concurrency and not self.stop_event.is_set():
                    futures[executor.submit(self._run_one_request, settings, next_index)] = next_index
                    next_index += 1
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            self.log_queue.put(("done", time.time() - started_at))

    def _run_one_request(self, settings: RequestSettings, index: int) -> Tuple[bool, float, str]:
        if self.stop_event.is_set():
            raise StopRequested("stop requested")
        started = time.time()
        client = ImageApiClient(settings.base_url, settings.api_key)
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
                return True, elapsed, "保存: " + "; ".join(saved_files)
            return False, elapsed, f"响应中未找到 b64_json 或 url: {compact_json(response)}"
        except Exception as exc:
            return False, time.time() - started, str(exc)

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

        payload = {"model": settings.model, "prompt": settings.prompt, "n": settings.image_count, "size": settings.size}
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
        fields: Dict[str, Any] = {"model": settings.model, "prompt": settings.prompt, "n": settings.image_count, "size": settings.size}
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
                file_path.write_bytes(base64.b64decode(b64))
                self._resize_saved_image_if_needed(file_path, settings)
                saved.append(str(file_path))
                continue
            url = item.get("url")
            if url:
                file_path = out_dir / f"{timestamp}_req{index:04d}_{image_idx}.{extension}"
                self._download_image(url, file_path, settings.api_key)
                self._resize_saved_image_if_needed(file_path, settings)
                saved.append(str(file_path))
        return saved

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

    def _download_image(self, url: str, out_path: Path, api_key: str) -> None:
        headers = {"User-Agent": "GPTImageGeneratorStressPanel/1.0"}
        if urllib.parse.urlparse(url).netloc == urllib.parse.urlparse(normalize_base_url(self.base_url_var.get())).netloc:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=180) as resp:
            out_path.write_bytes(resp.read())

    def _enqueue_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _poll_log_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "result":
                    idx, ok, elapsed, msg = payload
                    self.completed_count += 1
                    self.total_elapsed += elapsed
                    if ok:
                        self.success_count += 1
                        self._append_log(f"[#{idx}] 成功 {elapsed:.1f}s | {msg}")
                        if not self.batch_history_recorded and self.batch_prompt_for_history:
                            self._record_prompt_history(self.batch_prompt_for_history)
                            self.batch_history_recorded = True
                            self._append_log("已保存提示词历史")
                    else:
                        self.fail_count += 1
                        self._append_log(f"[#{idx}] 失败 {elapsed:.1f}s | {msg}")
                    self.progress_animating = False
                    self._set_real_progress()
                    self._update_stats()
                elif kind == "done":
                    elapsed_total = float(payload)
                    self.progress_animating = False
                    self.elapsed_timer_running = False
                    self.elapsed_var.set(f"耗时:{elapsed_total:.1f}s")
                    self._set_real_progress()
                    if self.completed_count >= self.total_requests:
                        self.progress.configure(value=100)
                    self._append_log(f"完成 | 成功:{self.success_count} 失败:{self.fail_count}/{self.total_requests} 总耗时:{elapsed_total:.1f}s")
                    self.running = False
                    self.batch_prompt_for_history = ""
                    self.batch_history_recorded = False
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_stats(self) -> None:
        avg = self.total_elapsed / self.completed_count if self.completed_count else 0.0
        self.stats_var.set(f"成功:{self.success_count} 失败:{self.fail_count} 平均:{avg:.1f}s")


def main() -> None:
    root = GPTImageApp()
    try:
        root.option_add("*Font", "Microsoft YaHei UI 9")
    except Exception:
        pass
    root.mainloop()


if __name__ == "__main__":
    main()
