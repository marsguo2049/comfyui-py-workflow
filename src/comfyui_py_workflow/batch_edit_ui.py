from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .batch_image_edit import (
    SUPPORTED_IMAGE_EXTENSIONS,
    BatchItemResult,
    BatchRunResult,
    QwenBatchImageEditor,
    default_qwen_workflow_path,
    discover_images,
)
from .client import ComfyUIClient


IMAGE_FILE_TYPES = [
    ("图片文件", " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_IMAGE_EXTENSIONS))),
    ("所有文件", "*.*"),
]


class BatchEditApp:
    def __init__(self, root: tk.Tk, *, initial_workflow: Path | None = None) -> None:
        self.root = root
        self.root.title("Qwen Image Edit 批处理")
        self.root.geometry("900x760")
        self.root.minsize(760, 660)

        self.files: list[Path] = []
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False

        self.server_var = tk.StringVar(value="http://127.0.0.1:8188")
        self.workflow_var = tk.StringVar(value=str(initial_workflow or default_qwen_workflow_path()))
        self.output_var = tk.StringVar(value=str(Path.cwd() / "outputs" / "batch-image-edit"))
        self.seed_var = tk.StringVar(value="43")
        self.timeout_var = tk.StringVar(value="900")
        self.increment_seed_var = tk.BooleanVar(value=True)
        self.recursive_var = tk.BooleanVar(value=False)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="请选择图片或文件夹")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.report_callback_exception = self._report_callback_exception
        self.root.after(100, self._drain_events)
        self.root.after(150, self._bring_to_front)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Hint.TLabel", foreground="#5d6470")

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(outer, text="Qwen Image Edit 2509 批量修改", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            outer,
            text="所有图片使用同一组提示词；任务会逐张上传到本机 ComfyUI 并把结果下载到指定目录。",
            style="Hint.TLabel",
        ).pack(anchor=tk.W, pady=(4, 12))

        connection = ttk.LabelFrame(outer, text="连接与工作流", padding=10)
        connection.pack(fill=tk.X)
        connection.columnconfigure(1, weight=1)
        ttk.Label(connection, text="ComfyUI 地址").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.server_entry = ttk.Entry(connection, textvariable=self.server_var)
        self.server_entry.grid(row=0, column=1, sticky=tk.EW)
        self.test_button = ttk.Button(connection, text="测试连接", command=self._test_connection)
        self.test_button.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(connection, text="API 工作流").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=(8, 0))
        self.workflow_entry = ttk.Entry(connection, textvariable=self.workflow_var)
        self.workflow_entry.grid(row=1, column=1, sticky=tk.EW, pady=(8, 0))
        self.workflow_button = ttk.Button(connection, text="浏览…", command=self._choose_workflow)
        self.workflow_button.grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        sources = ttk.LabelFrame(outer, text="输入图片", padding=10)
        sources.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        controls = ttk.Frame(sources)
        controls.pack(fill=tk.X, pady=(0, 8))
        self.add_files_button = ttk.Button(controls, text="添加多个文件…", command=self._add_files)
        self.add_files_button.pack(side=tk.LEFT)
        self.add_folder_button = ttk.Button(controls, text="添加文件夹…", command=self._add_folder)
        self.add_folder_button.pack(side=tk.LEFT, padx=(8, 0))
        self.remove_button = ttk.Button(controls, text="移除选中", command=self._remove_selected)
        self.remove_button.pack(side=tk.LEFT, padx=(8, 0))
        self.clear_button = ttk.Button(controls, text="清空", command=self._clear_files)
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(controls, text="包含子文件夹", variable=self.recursive_var).pack(side=tk.RIGHT)

        list_frame = ttk.Frame(sources)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.file_list = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=8)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scrollbar.set)
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        prompts = ttk.LabelFrame(outer, text="统一提示词", padding=10)
        prompts.pack(fill=tk.X, pady=(10, 0))
        prompts.columnconfigure(1, weight=1)
        ttk.Label(prompts, text="修改提示词 *").grid(row=0, column=0, sticky=tk.NW, padx=(0, 8))
        self.prompt_text = tk.Text(prompts, height=4, wrap=tk.WORD)
        self.prompt_text.grid(row=0, column=1, sticky=tk.EW)
        ttk.Label(prompts, text="负向提示词").grid(row=1, column=0, sticky=tk.NW, padx=(0, 8), pady=(8, 0))
        self.negative_text = tk.Text(prompts, height=2, wrap=tk.WORD)
        self.negative_text.grid(row=1, column=1, sticky=tk.EW, pady=(8, 0))
        ttk.Label(
            prompts,
            text="示例：移除水印并自然补全背景；移除画面中的人物；替换背景；统一一批图片的视觉风格。",
            style="Hint.TLabel",
        ).grid(row=2, column=1, sticky=tk.W, pady=(6, 0))

        output = ttk.LabelFrame(outer, text="输出与参数", padding=10)
        output.pack(fill=tk.X, pady=(10, 0))
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text="输出文件夹").grid(row=0, column=0, sticky=tk.W, padx=(0, 8))
        self.output_entry = ttk.Entry(output, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, columnspan=4, sticky=tk.EW)
        self.output_button = ttk.Button(output, text="选择…", command=self._choose_output)
        self.output_button.grid(row=0, column=5, padx=(8, 0))
        ttk.Label(output, text="基础种子").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        self.seed_entry = ttk.Entry(output, textvariable=self.seed_var, width=14)
        self.seed_entry.grid(row=1, column=1, sticky=tk.W, pady=(8, 0))
        self.increment_check = ttk.Checkbutton(output, text="每张图片种子 +1", variable=self.increment_seed_var)
        self.increment_check.grid(row=1, column=2, sticky=tk.W, padx=(12, 0), pady=(8, 0))
        ttk.Label(output, text="单张超时（秒）").grid(row=1, column=3, sticky=tk.E, padx=(12, 8), pady=(8, 0))
        self.timeout_entry = ttk.Entry(output, textvariable=self.timeout_var, width=9)
        self.timeout_entry.grid(row=1, column=4, sticky=tk.W, pady=(8, 0))
        self.overwrite_check = ttk.Checkbutton(output, text="覆盖同名结果", variable=self.overwrite_var)
        self.overwrite_check.grid(row=1, column=5, sticky=tk.E, padx=(8, 0), pady=(8, 0))

        run_row = ttk.Frame(outer)
        run_row.pack(fill=tk.X, pady=(12, 0))
        self.start_button = ttk.Button(run_row, text="开始批处理", command=self._start)
        self.start_button.pack(side=tk.LEFT)
        self.cancel_button = ttk.Button(run_row, text="停止后续任务", command=self._cancel, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT, padx=(8, 0))
        self.progress = ttk.Progressbar(run_row, mode="determinate")
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(14, 0))

        ttk.Label(outer, textvariable=self.status_var).pack(anchor=tk.W, pady=(8, 4))
        self.log_text = tk.Text(outer, height=5, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.X)

        self.mutable_widgets = [
            self.server_entry,
            self.test_button,
            self.workflow_entry,
            self.workflow_button,
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.prompt_text,
            self.negative_text,
            self.output_entry,
            self.output_button,
            self.seed_entry,
            self.increment_check,
            self.timeout_entry,
            self.overwrite_check,
        ]

    def _add_files(self) -> None:
        selected = filedialog.askopenfilenames(title="选择要处理的图片", filetypes=IMAGE_FILE_TYPES)
        self._append_files(discover_images(selected))

    def _add_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择图片文件夹", mustexist=True)
        if selected:
            self._append_files(discover_images([selected], recursive=self.recursive_var.get()))

    def _append_files(self, paths: list[Path]) -> None:
        known = {str(path).casefold() for path in self.files}
        for path in paths:
            if str(path).casefold() not in known:
                known.add(str(path).casefold())
                self.files.append(path)
                self.file_list.insert(tk.END, str(path))
        self.status_var.set(f"已选择 {len(self.files)} 张图片")

    def _remove_selected(self) -> None:
        for index in reversed(self.file_list.curselection()):
            del self.files[index]
            self.file_list.delete(index)
        self.status_var.set(f"已选择 {len(self.files)} 张图片")

    def _clear_files(self) -> None:
        self.files.clear()
        self.file_list.delete(0, tk.END)
        self.status_var.set("请选择图片或文件夹")

    def _choose_workflow(self) -> None:
        selected = filedialog.askopenfilename(
            title="选择 ComfyUI API 工作流",
            filetypes=[("JSON 工作流", "*.json"), ("所有文件", "*.*")],
            initialfile=Path(self.workflow_var.get()).name,
        )
        if selected:
            self.workflow_var.set(selected)

    def _choose_output(self) -> None:
        initial = Path(self.output_var.get()).expanduser()
        selected = filedialog.askdirectory(
            title="选择输出文件夹",
            initialdir=str(initial if initial.is_dir() else initial.parent),
        )
        if selected:
            self.output_var.set(selected)

    def _test_connection(self) -> None:
        server = self.server_var.get().strip()
        self.test_button.configure(state=tk.DISABLED)
        self.status_var.set("正在测试 ComfyUI 连接…")

        def worker() -> None:
            try:
                ComfyUIClient(server).check_health()
            except Exception as exc:
                self.events.put(("health_error", f"{type(exc).__name__}: {exc}"))
            else:
                self.events.put(("health_ok", server))

        threading.Thread(target=worker, daemon=True).start()

    def _start(self) -> None:
        try:
            settings = self._settings()
        except (ValueError, OSError) as exc:
            messagebox.showerror("无法开始", str(exc), parent=self.root)
            return
        self.cancel_event.clear()
        self.progress.configure(maximum=len(self.files), value=0)
        self._clear_log()
        self._set_running(True)
        self.status_var.set("正在准备批处理…")

        def worker() -> None:
            try:
                client = ComfyUIClient(settings["server"])
                result = QwenBatchImageEditor(client).run(
                    images=settings["files"],
                    output_dir=settings["output"],
                    prompt=settings["prompt"],
                    negative_prompt=settings["negative_prompt"],
                    workflow_path=settings["workflow"],
                    base_seed=settings["seed"],
                    increment_seed=settings["increment_seed"],
                    timeout_seconds=settings["timeout"],
                    overwrite=settings["overwrite"],
                    cancel_event=self.cancel_event,
                    on_status=lambda value: self.events.put(("status", value)),
                    on_progress=lambda done, total, item: self.events.put(
                        ("progress", (done, total, item))
                    ),
                )
            except Exception as exc:
                self.events.put(("run_error", f"{type(exc).__name__}: {exc}"))
            else:
                self.events.put(("done", result))

        threading.Thread(target=worker, daemon=True).start()

    def _settings(self) -> dict[str, Any]:
        if not self.files:
            raise ValueError("请先添加至少一张图片")
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            raise ValueError("请输入修改提示词")
        workflow = Path(self.workflow_var.get().strip()).expanduser()
        if not workflow.is_file():
            raise ValueError(f"找不到 API 工作流：{workflow}")
        output = Path(self.output_var.get().strip()).expanduser()
        if not str(output):
            raise ValueError("请选择输出文件夹")
        seed = int(self.seed_var.get())
        timeout = float(self.timeout_var.get())
        if seed < 0:
            raise ValueError("基础种子不能为负数")
        if timeout <= 0:
            raise ValueError("超时时间必须大于 0")
        return {
            "files": tuple(self.files),
            "prompt": prompt,
            "negative_prompt": self.negative_text.get("1.0", tk.END).strip(),
            "workflow": workflow,
            "output": output,
            "server": self.server_var.get().strip(),
            "seed": seed,
            "timeout": timeout,
            "increment_seed": self.increment_seed_var.get(),
            "overwrite": self.overwrite_var.get(),
        }

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state=tk.DISABLED)
        self.status_var.set("已请求停止；当前图片完成后不再提交后续任务")

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "status":
                    self.status_var.set(str(payload))
                elif event == "progress":
                    done, total, item = payload
                    self.progress.configure(maximum=total, value=done)
                    self._log_item(item)
                elif event == "done":
                    self._finish(payload)
                elif event == "run_error":
                    self._set_running(False)
                    self.status_var.set("批处理未完成")
                    self._append_log(f"错误：{payload}")
                    messagebox.showerror("批处理错误", str(payload), parent=self.root)
                elif event == "health_ok":
                    self.test_button.configure(state=tk.NORMAL)
                    self.status_var.set(f"连接成功：{payload}")
                elif event == "health_error":
                    self.test_button.configure(state=tk.NORMAL)
                    self.status_var.set("ComfyUI 连接失败")
                    messagebox.showerror("连接失败", str(payload), parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _finish(self, result: BatchRunResult) -> None:
        self._set_running(False)
        if result.cancelled:
            self.status_var.set(
                f"已停止：成功 {result.succeeded_count}，失败 {result.failed_count}"
            )
        else:
            self.status_var.set(
                f"处理完成：成功 {result.succeeded_count}，失败 {result.failed_count}"
            )
        if result.failed_count:
            messagebox.showwarning("批处理完成", self.status_var.get(), parent=self.root)
        elif not result.cancelled:
            messagebox.showinfo("批处理完成", self.status_var.get(), parent=self.root)

    def _log_item(self, item: BatchItemResult) -> None:
        if item.succeeded:
            self._append_log(f"✓ {item.source.name}  →  {item.destination}")
        else:
            self._append_log(f"✗ {item.source.name}  →  {item.error}")

    def _append_log(self, value: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, value + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_running(self, running: bool) -> None:
        self.running = running
        state = tk.DISABLED if running else tk.NORMAL
        for widget in self.mutable_widgets:
            widget.configure(state=state)
        self.start_button.configure(state=state)
        self.cancel_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _on_close(self) -> None:
        if self.running and not messagebox.askyesno(
            "任务仍在运行",
            "关闭窗口会停止提交后续图片；ComfyUI 中当前任务可能仍会继续。确定关闭吗？",
            parent=self.root,
        ):
            return
        self.cancel_event.set()
        self.root.destroy()

    def _bring_to_front(self) -> None:
        """Make a newly launched window visible above terminals and IDEs."""

        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

    def _report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        error_log_path().write_text(details, encoding="utf-8")
        messagebox.showerror(
            "界面运行错误",
            f"{exc_type.__name__}: {exc_value}\n\n详细信息已写入：\n{error_log_path()}",
            parent=self.root,
        )


def error_log_path() -> Path:
    return Path.cwd() / "batch-image-edit-ui-error.log"


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen Image Edit offline batch UI")
    parser.add_argument("--workflow", type=Path, default=default_qwen_workflow_path())
    args = parser.parse_args()
    try:
        root = tk.Tk()
        BatchEditApp(root, initial_workflow=args.workflow)
        root.mainloop()
    except Exception as exc:
        details = traceback.format_exc()
        error_log_path().write_text(details, encoding="utf-8")
        try:
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror(
                "Qwen 批处理界面无法启动",
                f"{type(exc).__name__}: {exc}\n\n详细信息已写入：\n{error_log_path()}",
                parent=fallback,
            )
            fallback.destroy()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
