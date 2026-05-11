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
import mimetypes
import queue
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

APP_TITLE = "GPT 图像生成器 - 压力测试面板"
MAX_INPUT_BYTES = 30 * 1024 * 1024
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-image-2"
CONFIG_FILE = "config.ini"

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
QUALITY_VALUES = ["自动", "低", "中", "高"]
QUALITY_TO_API = {"自动": "auto", "低": "low", "中": "medium", "高": "high"}
API_TO_QUALITY = {v: k for k, v in QUALITY_TO_API.items()}
FORMAT_VALUES = ["png", "jpeg", "webp"]


@dataclass
class RequestSettings:
    base_url: str
    api_key: str
    mode: str
    image_paths: List[str]
    prompt: str
    size: str
    quality: str
    output_format: str
    compression: int
    model: str
    output_dir: str


class ImageApiError(RuntimeError):
    pass


class StopRequested(RuntimeError):
    pass


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


def quality_label_to_api(value: str) -> str:
    value = (value or "高").strip()
    return QUALITY_TO_API.get(value, value)


def quality_api_to_label(value: str) -> str:
    value = (value or "high").strip()
    return API_TO_QUALITY.get(value, value)


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
        self.geometry("930x890")
        self.minsize(880, 760)

        self.config_path = app_base_dir() / CONFIG_FILE
        self.log_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.selected_images: List[str] = []
        self.running = False
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
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
        self.base_url_var = tk.StringVar(value=DEFAULT_BASE_URL)
        self.api_key_var = tk.StringVar(value="")
        self.show_key_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value="edit")
        self.size_preset_var = tk.StringVar(value=PRESET_SIZES[0])
        self.custom_size_var = tk.StringVar(value="")
        self.quality_var = tk.StringVar(value="高")
        self.format_var = tk.StringVar(value="jpeg")
        self.compression_var = tk.IntVar(value=100)
        self.model_var = tk.StringVar(value=DEFAULT_MODEL)
        self.total_requests_var = tk.IntVar(value=1)
        self.concurrency_var = tk.IntVar(value=1)
        default_output = str((Path.cwd() / "output").resolve())
        self.output_dir_var = tk.StringVar(value=default_output)
        self.stats_var = tk.StringVar(value="成功:0 失败:0 / 0  平均:0.0s")

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
        ttk.Label(frame, text="接口地址:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(frame, textvariable=self.base_url_var).grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        ttk.Label(frame, text="API Key:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        self.api_key_entry = ttk.Entry(frame, textvariable=self.api_key_var, show="*")
        self.api_key_entry.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Checkbutton(frame, text="显示", variable=self.show_key_var, command=self._toggle_key).grid(row=1, column=2, padx=8)
        ttk.Button(frame, text="保存配置", command=self._save_config).grid(row=1, column=3, padx=(8, 0))

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
        self.image_button = ttk.Button(frame, text="选择图片", command=self._select_images)
        self.image_button.grid(row=0, column=1)

    def _build_prompt_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="提示词", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        self.prompt_text = tk.Text(frame, height=3, wrap="word", undo=True)
        self.prompt_text.grid(row=0, column=0, sticky="ew")
        self.prompt_text.insert("1.0", "输入你的图片生成提示词；图生图模式下会结合所选图片进行编辑或参考。")

    def _build_params_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="参数", padding=6)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(7, weight=1)
        ttk.Label(frame, text="尺寸预设:").grid(row=0, column=0, sticky="w", pady=3)
        self.size_menu = tk.OptionMenu(frame, self.size_preset_var, *PRESET_SIZES)
        self.size_menu.configure(width=24)
        self.size_menu.grid(row=0, column=1, sticky="w", padx=(4, 18), pady=3)
        ttk.Label(frame, text="自定义尺寸:").grid(row=0, column=2, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.custom_size_var, width=13).grid(row=0, column=3, sticky="w", padx=(4, 8), pady=3)
        ttk.Label(frame, text="(宽高须为 16 的倍数，比例 <= 3:1)").grid(row=0, column=4, sticky="w", pady=3)
        ttk.Label(frame, text="质量:").grid(row=1, column=0, sticky="w", pady=3)
        self.quality_menu = tk.OptionMenu(frame, self.quality_var, *QUALITY_VALUES)
        self.quality_menu.configure(width=8)
        self.quality_menu.grid(row=1, column=1, sticky="w", padx=(4, 18), pady=3)
        ttk.Label(frame, text="格式:").grid(row=1, column=2, sticky="w", pady=3)
        self.format_menu = tk.OptionMenu(frame, self.format_var, *FORMAT_VALUES)
        self.format_menu.configure(width=8)
        self.format_menu.grid(row=1, column=3, sticky="w", padx=(4, 18), pady=3)
        ttk.Label(frame, text="压缩(jpeg/webp):").grid(row=1, column=4, sticky="w", pady=3)
        ttk.Spinbox(frame, from_=0, to=100, textvariable=self.compression_var, width=6).grid(row=1, column=5, sticky="w", padx=(4, 0), pady=3)
        ttk.Label(frame, text="模型:").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Entry(frame, textvariable=self.model_var, width=22).grid(row=2, column=1, sticky="w", padx=(4, 18), pady=3)

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

    def _build_control_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(frame, text="开始生成", command=self._start)
        self.start_button.grid(row=0, column=0, sticky="w")
        self.stop_button = ttk.Button(frame, text="停止", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(12, 18))
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=1, value=0)
        self.progress.grid(row=0, column=2, sticky="ew", padx=(0, 12))
        ttk.Label(frame, textvariable=self.stats_var).grid(row=0, column=3, sticky="e")

    def _build_log_frame(self, parent: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(parent, text="日志", padding=6)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(frame, height=16, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

    def _toggle_key(self) -> None:
        self.api_key_entry.configure(show="" if self.show_key_var.get() else "*")

    def _on_mode_change(self) -> None:
        if self.mode_var.get() == "generate":
            if hasattr(self, "image_entry"):
                self.image_entry.configure(state="disabled")
            if hasattr(self, "image_button"):
                self.image_button.configure(state="disabled")
        else:
            if hasattr(self, "image_entry"):
                self.image_entry.configure(state="readonly")
            if hasattr(self, "image_button"):
                self.image_button.configure(state="normal")
        self._refresh_image_label()

    def _load_config(self) -> None:
        cfg = configparser.ConfigParser()
        if self.config_path.exists():
            try:
                cfg.read(self.config_path, encoding="utf-8")
                sec = cfg["app"] if cfg.has_section("app") else {}
                self.base_url_var.set(sec.get("base_url", DEFAULT_BASE_URL))
                self.api_key_var.set(sec.get("api_key", ""))
                self.model_var.set(sec.get("model", DEFAULT_MODEL))
                self.output_dir_var.set(sec.get("output_dir", self.output_dir_var.get()))
                saved_size = sec.get("size_preset", PRESET_SIZES[0])
                self.size_preset_var.set(PRESET_SIZES[0] if saved_size.startswith(("auto", "自动")) else saved_size)
                self.custom_size_var.set(sec.get("custom_size", ""))
                self.quality_var.set(quality_api_to_label(sec.get("quality", "high")))
                self.format_var.set(sec.get("output_format", "jpeg"))
                self.compression_var.set(safe_int(sec.get("compression", 100), 100, 0, 100))
                self.mode_var.set(sec.get("mode", "edit"))
                self._enqueue_log(f"已从 {self.config_path.name} 加载配置（API Key: {self._masked_key()}）")
            except Exception as exc:
                self._enqueue_log(f"加载配置失败: {exc}")
        else:
            self._enqueue_log("未找到 config.ini，已使用默认配置")

    def _save_config(self) -> None:
        cfg = configparser.ConfigParser()
        cfg["app"] = {
            "base_url": normalize_base_url(self.base_url_var.get()),
            "api_key": self.api_key_var.get().strip(),
            "model": self.model_var.get().strip() or DEFAULT_MODEL,
            "output_dir": self.output_dir_var.get().strip(),
            "size_preset": self.size_preset_var.get(),
            "custom_size": self.custom_size_var.get().strip(),
            "quality": quality_label_to_api(self.quality_var.get()),
            "output_format": self.format_var.get(),
            "compression": str(safe_int(self.compression_var.get(), 100, 0, 100)),
            "mode": self.mode_var.get(),
        }
        try:
            with self.config_path.open("w", encoding="utf-8") as f:
                cfg.write(f)
            self._enqueue_log(f"配置已保存到 {self.config_path}")
            messagebox.showinfo("保存配置", f"配置已保存到:\n{self.config_path}")
        except Exception as exc:
            messagebox.showerror("保存配置失败", str(exc))

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

    def _refresh_image_label(self) -> None:
        total = sum(Path(p).stat().st_size for p in self.selected_images if Path(p).exists())
        if self.mode_var.get() == "generate":
            if self.selected_images:
                self.image_label_var.set(f"文生图模式无需选择图片（已选 {len(self.selected_images)} 张，生成时忽略）")
            else:
                self.image_label_var.set("文生图模式无需选择图片")
            return
        if self.selected_images:
            self.image_label_var.set(f"已选择 {len(self.selected_images)} 张图片，合计 {human_size(total)}")
        else:
            self.image_label_var.set("未选择图片")

    def _select_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir_var.get() or str(Path.cwd()))
        if path:
            self.output_dir_var.set(path)

    def _current_settings(self) -> RequestSettings:
        custom_size = self.custom_size_var.get().strip()
        size = custom_size if custom_size else strip_auto_label(self.size_preset_var.get())
        mode = self.mode_var.get()
        return RequestSettings(
            base_url=normalize_base_url(self.base_url_var.get()),
            api_key=self.api_key_var.get().strip(),
            mode=mode,
            image_paths=[] if mode == "generate" else list(self.selected_images),
            prompt=self.prompt_text.get("1.0", "end").strip(),
            size=size,
            quality=quality_label_to_api(self.quality_var.get()),
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
        self.success_count = 0
        self.fail_count = 0
        self.completed_count = 0
        self.total_elapsed = 0.0
        self.total_requests = safe_int(self.total_requests_var.get(), 1, 1, 10000)
        concurrency = min(safe_int(self.concurrency_var.get(), 1, 1, 100), self.total_requests)
        self.progress.configure(maximum=self.total_requests, value=0)
        self._update_stats()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._enqueue_log(f"开始 | Images API 测试 | 总数:{self.total_requests} 并发:{concurrency} 尺寸:{settings.size} 质量:{settings.quality} 格式:{settings.output_format}")
        self._enqueue_log(f"接口: {settings.base_url}/images/{'edits' if settings.mode == 'edit' else 'generations'}")
        self.worker_thread = threading.Thread(target=self._run_batch, args=(settings, self.total_requests, concurrency), daemon=True)
        self.worker_thread.start()

    def _stop(self) -> None:
        if self.running:
            self.stop_event.set()
            self._enqueue_log("已请求停止：未开始的请求将不再提交，已发出的请求会等待返回。")
            self.stop_button.configure(state="disabled")

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
        payload: Dict[str, Any] = {"model": settings.model, "prompt": settings.prompt, "n": 1, "size": settings.size}
        if settings.quality:
            payload["quality"] = settings.quality
        if settings.output_format:
            payload["output_format"] = settings.output_format
        if settings.output_format in {"jpeg", "webp"}:
            payload["output_compression"] = settings.compression
        return payload

    def _build_edit_fields(self, settings: RequestSettings) -> Dict[str, Any]:
        fields: Dict[str, Any] = {"model": settings.model, "prompt": settings.prompt, "n": 1, "size": settings.size}
        if settings.quality:
            fields["quality"] = settings.quality
        if settings.output_format:
            fields["output_format"] = settings.output_format
        if settings.output_format in {"jpeg", "webp"}:
            fields["output_compression"] = settings.compression
        return fields

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
                saved.append(str(file_path))
                continue
            url = item.get("url")
            if url:
                file_path = out_dir / f"{timestamp}_req{index:04d}_{image_idx}.{extension}"
                self._download_image(url, file_path, settings.api_key)
                saved.append(str(file_path))
        return saved

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
                    else:
                        self.fail_count += 1
                        self._append_log(f"[#{idx}] 失败 {elapsed:.1f}s | {msg}")
                    self.progress.configure(value=self.completed_count)
                    self._update_stats()
                elif kind == "done":
                    elapsed_total = float(payload)
                    self._append_log(f"完成 | 成功:{self.success_count} 失败:{self.fail_count}/{self.total_requests} 总耗时:{elapsed_total:.1f}s")
                    self.running = False
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
        self.stats_var.set(f"成功:{self.success_count} 失败:{self.fail_count} / {self.total_requests}  平均:{avg:.1f}s")


def main() -> None:
    root = GPTImageApp()
    try:
        root.option_add("*Font", "Microsoft YaHei UI 9")
    except Exception:
        pass
    root.mainloop()


if __name__ == "__main__":
    main()
