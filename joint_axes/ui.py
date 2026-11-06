"""Kompakt Tkinter kullanıcı arayüzü."""

from __future__ import annotations

import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .info import InfoWindow
from .inputs import split_joint_tokens
from .meta import APP_NAME, APP_VERSION
from .models import AxisPlan, JointAxisResult, Vector2
from .preview3d import Preview3D
from .service import ApplyReport, JointAxesService
from .window_theme import apply_title_bar_theme

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f4f5f7",
        "panel": "#ffffff",
        "text": "#1d2433",
        "muted": "#69707d",
        "border": "#d9dee6",
        "button_border": "#c5cdd8",
        "accent": "#c8102e",
        "accent_hover": "#a80d26",
        "accent_text": "#ffffff",
        "input_bg": "#ffffff",
        "input_fg": "#1d2433",
        "heading_bg": "#eef1f4",
        "heading_fg": "#4b5563",
        "selection": "#fbe3e8",
        "selection_fg": "#1d2433",
        "warn": "#8a5a00",
        "error": "#b42318",
        "ok": "#18794e",
        "button_bg": "#ffffff",
        "button_hover": "#eef1f4",
        "vector": "#1f5fbf",
        "axis_x": "#c0392b",
        "axis_y": "#1f8b4c",
        "axis_z": "#2f6fed",
    },
    "dark": {
        "bg": "#111418",
        "panel": "#181c22",
        "text": "#e7e9ec",
        "muted": "#96a0ad",
        "border": "#2a3038",
        "button_border": "#3c4653",
        "accent": "#e23b52",
        "accent_hover": "#c92f45",
        "accent_text": "#ffffff",
        "input_bg": "#1d222a",
        "input_fg": "#e7e9ec",
        "heading_bg": "#20262e",
        "heading_fg": "#b2bac5",
        "selection": "#3b2027",
        "selection_fg": "#ffffff",
        "warn": "#e8b45c",
        "error": "#ff7b72",
        "ok": "#5dd39e",
        "button_bg": "#222831",
        "button_hover": "#2d3642",
        "vector": "#6aa9ff",
        "axis_x": "#ff6b5b",
        "axis_y": "#5dd39e",
        "axis_z": "#7aa7ff",
    },
}

TARGET_AXES = {
    "X (1)": "x",
    "Y (2)": "y",
    "Z (3)": "z",
}

_ENTRY_SPLIT = re.compile(r"[,;\s]+")


def _asset_path(name: str) -> Path:
    """Kaynak çalıştırmada ve PyInstaller exe içinde ikon yolunu bulur."""

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if getattr(sys, "frozen", False):
        return base / "joint_axes" / "assets" / name
    return base / "assets" / name


def _apply_window_icon(root: tk.Tk) -> None:
    icon = _asset_path("app.ico")
    if icon.exists():
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass

    png = _asset_path("tiger.png")
    if png.exists():
        try:
            image = tk.PhotoImage(file=str(png))
            root.iconphoto(True, image)
            root._app_icon = image  # type: ignore[attr-defined]
        except tk.TclError:
            pass


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def _fmt_vector(vector: Vector2 | None) -> str:
    if vector is None:
        return "-"
    return f"{vector.x:.3f}, {vector.y:.3f}"


def _fmt_vector3(vector: tuple[float, float, float] | None) -> str:
    if vector is None:
        return "-"
    return f"{vector[0]:.3f}, {vector[1]:.3f}, {vector[2]:.3f}"


def _fmt_angle(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _axis_label(axis: str) -> str:
    return {"x": "X (1)", "y": "Y (2)", "z": "Z (3)"}.get(axis, axis.upper())


def _natural_key(name: str) -> list[tuple[int, int | str]]:
    """Joint adlarını 2, 10, 100 sırasıyla karşılaştırır."""

    return [
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", name)
        if part
    ]


class _TreeGrid:
    """Treeview üzerine ince satır/sütun çizgileri yerleştirir."""

    def __init__(self, container: tk.Misc, tree: ttk.Treeview, color: str) -> None:
        self.container = container
        self.tree = tree
        self.color = color
        self.lines: list[tk.Frame] = []

    def set_color(self, color: str) -> None:
        self.color = color
        for line in self.lines:
            line.configure(bg=color)

    def _line(self, x: int, y: int, width: int, height: int) -> None:
        line = tk.Frame(
            self.container,
            bg=self.color,
            bd=0,
            highlightthickness=0,
            takefocus=0,
        )
        line.place(x=x, y=y, width=width, height=height)
        self.lines.append(line)

    def refresh(self) -> None:
        for line in self.lines:
            line.destroy()
        self.lines.clear()

        width = self.tree.winfo_width()
        height = self.tree.winfo_height()
        if width <= 2 or height <= 2:
            return

        x = 0
        for column in self.tree["columns"][:-1]:
            x += int(self.tree.column(column, "width"))
            if 0 < x < width - 1:
                self._line(x, 0, 1, height)

        header_bottom = 0
        for y in range(min(height, 80)):
            if self.tree.identify_row(y):
                header_bottom = y
                break
        if header_bottom > 1:
            self._line(0, header_bottom - 1, width, 1)

        for item in self.tree.get_children():
            bbox = self.tree.bbox(item)
            if not bbox:
                continue
            _, y, _, row_height = bbox
            bottom = y + row_height - 1
            if header_bottom <= bottom < height:
                self._line(0, bottom, width, 1)


class JointAxesWindow(ttk.Frame):
    """Ana pencere."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=12, style="App.TFrame")
        self.service = JointAxesService()
        self.plan: AxisPlan | None = None
        self.joint_names: list[str] = []
        self._catalog: list[str] = []
        self._catalog_loaded = False
        self._entry_typed = ""
        self._info_window: InfoWindow | None = None
        self._theme_name = "light"
        self._action_buttons: list[ttk.Widget] = []
        self._card_borders: list[tk.Frame] = []

        self.conn_var = tk.StringVar(value="SAP2000 · bağlantı yok")
        self.reverse_var = tk.BooleanVar(value=False)
        self.use_3d_var = tk.BooleanVar(value=False)
        self.axis_var = tk.StringVar(value="X (1)")
        self.count_var = tk.StringVar(value="0 joint")
        self.sequence_count_var = tk.StringVar(value="0 joint")
        self.entry_hint_var = tk.StringVar(
            value="Joint önerileri için SAP2000 bağlantısı kurun."
        )
        self.status_var = tk.StringVar(
            value="SAP2000 seçimini alın veya joint adlarını ekleyin."
        )

        self._build_layout()
        self._bind_shortcuts()
        self._apply_theme("light")

    def _bind_shortcuts(self) -> None:
        root = self.winfo_toplevel()
        root.bind("<Control-i>", lambda _event: self._load_selection(), add="+")
        root.bind("<Control-I>", lambda _event: self._load_selection(), add="+")
        root.bind("<F5>", lambda _event: self._load_all_joints(), add="+")

    # ------------------------------------------------------------------ layout

    def _build_layout(self) -> None:
        self.pack(fill="both", expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=3)
        self.rowconfigure(4, weight=2)

        self._build_header()
        self._build_body()
        self._build_options()
        self._build_results()
        self._build_status()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        brand = ttk.Frame(header, style="App.TFrame")
        brand.grid(row=0, column=0, sticky="w")
        ttk.Label(brand, text="Joint Axes", style="Title.TLabel").pack(side="left")
        ttk.Label(brand, text=APP_VERSION, style="Badge.TLabel").pack(
            side="left", padx=(7, 0), pady=(2, 0)
        )
        ttk.Label(
            brand,
            text="SAP2000 · 2B/3B normal hizalama",
            style="Muted.TLabel",
        ).pack(side="left", padx=(8, 0), pady=(3, 0))

        header_right = ttk.Frame(header, style="App.TFrame")
        header_right.grid(row=0, column=1, sticky="e")
        ttk.Label(header_right, textvariable=self.conn_var, style="Muted.TLabel").pack(
            side="left", padx=(0, 10)
        )
        self.connect_button = ttk.Button(
            header_right,
            text="Bağlantıyı test et",
            style="Tool.TButton",
            command=self._test_connection,
        )
        self.connect_button.pack(side="left")
        self.info_button = ttk.Button(
            header_right,
            text="Info",
            style="Tool.TButton",
            command=self._show_info,
        )
        self.info_button.pack(side="left", padx=(6, 0))
        self.theme_button = ttk.Button(
            header_right,
            text="Karanlık tema",
            style="Tool.TButton",
            command=self._toggle_theme,
        )
        self.theme_button.pack(side="left", padx=(6, 0))

    def _build_body(self) -> None:
        body = ttk.Frame(self, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        body.columnconfigure(0, weight=0, minsize=382)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        sequence_border, self.sequence_panel = self._make_card(body)
        sequence_border.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_sequence(self.sequence_panel)

        preview_border, self.preview_panel = self._make_card(body)
        preview_border.grid(row=0, column=1, sticky="nsew")
        self._build_preview(self.preview_panel)

    def _make_card(self, parent: tk.Misc) -> tuple[tk.Frame, ttk.Frame]:
        border = tk.Frame(parent, bd=0, highlightthickness=0)
        inner = ttk.Frame(border, style="Panel.TFrame", padding=10)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._card_borders.append(border)
        return border, inner

    def _build_sequence(self, panel: ttk.Frame) -> None:
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(4, weight=1)

        head = ttk.Frame(panel, style="Panel.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="Joint sırası", style="PanelTitle.TLabel").pack(
            side="left"
        )
        ttk.Label(
            head, textvariable=self.sequence_count_var, style="PanelMuted.TLabel"
        ).pack(side="left", padx=(7, 0), pady=(1, 0))

        ttk.Label(
            panel,
            text=(
                "Seçili jointleri al (Ctrl+I) · Tümünü al (F5). "
                "Yola göre sırala, sonra oklarla elle düzeltin."
            ),
            style="PanelHint.TLabel",
            wraplength=400,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(3, 7))

        pick_row = ttk.Frame(panel, style="Panel.TFrame")
        pick_row.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        pick_row.columnconfigure(0, weight=1, uniform="import")
        pick_row.columnconfigure(1, weight=1, uniform="import")
        self.selection_button = ttk.Button(
            pick_row,
            text="Seçili jointleri al",
            style="AccentOutline.TButton",
            command=self._load_selection,
        )
        self.selection_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.all_button = ttk.Button(
            pick_row,
            text="Tümünü al",
            style="Tool.TButton",
            command=self._load_all_joints,
        )
        self.all_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        sort_row = ttk.Frame(panel, style="Panel.TFrame")
        sort_row.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        sort_row.columnconfigure(0, weight=1, uniform="sort")
        sort_row.columnconfigure(1, weight=1, uniform="sort")
        self.geometry_sort_button = ttk.Button(
            sort_row,
            text="Yola göre sırala",
            style="Tool.TButton",
            command=self._sort_by_geometry,
        )
        self.geometry_sort_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.sort_button = ttk.Button(
            sort_row,
            text="Ada göre sırala",
            style="Tool.TButton",
            command=self._sort_by_name,
        )
        self.sort_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        list_border = tk.Frame(panel, bd=0, highlightthickness=1)
        list_border.grid(row=4, column=0, sticky="nsew")
        list_border.columnconfigure(0, weight=1)
        list_border.rowconfigure(0, weight=1)
        self.sequence_border = list_border

        self.sequence_list = ttk.Treeview(
            list_border,
            columns=("order", "name"),
            show="headings",
            selectmode="extended",
            style="Sequence.Treeview",
            height=7,
        )
        self.sequence_list.heading("order", text="Sıra")
        self.sequence_list.heading("name", text="Joint")
        self.sequence_list.column(
            "order", width=52, minwidth=44, anchor="center", stretch=False
        )
        self.sequence_list.column(
            "name", width=250, minwidth=90, anchor="w", stretch=True
        )
        self.sequence_list.grid(row=0, column=0, sticky="nsew")
        list_scroll = ttk.Scrollbar(
            list_border,
            orient="vertical",
            command=self.sequence_list.yview,
            style="Vertical.TScrollbar",
        )
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.sequence_list.configure(yscrollcommand=list_scroll.set)
        self.sequence_list.bind("<Delete>", lambda _event: self._remove_selected())

        ttk.Label(panel, text="Joint ara / ekle", style="PanelMuted.TLabel").grid(
            row=5, column=0, sticky="w", pady=(8, 2)
        )

        entry_row = ttk.Frame(panel, style="Panel.TFrame")
        entry_row.grid(row=6, column=0, sticky="ew", pady=(0, 2))
        entry_row.columnconfigure(0, weight=1)
        self.joint_entry = ttk.Combobox(
            entry_row,
            state="normal",
            values=(),
            font=("Segoe UI", 9),
        )
        self.joint_entry.grid(row=0, column=0, sticky="ew")
        self.joint_entry.bind("<Return>", self._add_from_entry)
        self.joint_entry.bind("<KeyRelease>", self._on_entry_key)
        self.joint_entry.bind("<<ComboboxSelected>>", self._on_entry_selected)
        self.joint_entry.bind("<FocusIn>", self._on_entry_focus)
        self.add_button = ttk.Button(
            entry_row,
            text="Ekle",
            style="AccentOutline.TButton",
            command=self._add_from_entry,
        )
        self.add_button.grid(row=0, column=1, padx=(6, 0))

        ttk.Label(
            panel,
            textvariable=self.entry_hint_var,
            style="PanelHint.TLabel",
        ).grid(row=7, column=0, sticky="w", pady=(0, 8))

        order_row = ttk.Frame(panel, style="Panel.TFrame")
        order_row.grid(row=8, column=0, sticky="ew")
        for index in range(5):
            order_row.columnconfigure(index, weight=1, uniform="order")
        self.up_button = ttk.Button(
            order_row,
            text="↑ Yukarı",
            style="Compact.TButton",
            command=lambda: self._move_selected(-1),
        )
        self.up_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.down_button = ttk.Button(
            order_row,
            text="↓ Aşağı",
            style="Compact.TButton",
            command=lambda: self._move_selected(1),
        )
        self.down_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.remove_button = ttk.Button(
            order_row,
            text="Sil",
            style="Compact.TButton",
            command=self._remove_selected,
        )
        self.remove_button.grid(row=0, column=2, sticky="ew", padx=3)
        self.reverse_button = ttk.Button(
            order_row,
            text="Ters çevir",
            style="Compact.TButton",
            command=self._reverse_sequence,
        )
        self.reverse_button.grid(row=0, column=3, sticky="ew", padx=3)
        self.clear_button = ttk.Button(
            order_row,
            text="Temizle",
            style="Compact.TButton",
            command=self._clear_sequence,
        )
        self.clear_button.grid(row=0, column=4, sticky="ew", padx=(3, 0))

    def _build_preview(self, panel: ttk.Frame) -> None:
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        head = ttk.Frame(panel, style="Panel.TFrame")
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="3B önizleme", style="PanelTitle.TLabel").pack(side="left")
        self.reset_view_button = ttk.Button(
            head,
            text="Görünümü sıfırla",
            style="Compact.TButton",
            command=self._reset_preview_view,
        )
        self.reset_view_button.pack(side="right")

        ttk.Label(
            panel,
            text="Teğet hattı, mavi normal okları ve seçilen local eksen yönü.",
            style="PanelHint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 6))

        self.preview3d = Preview3D(panel, THEMES["light"])
        self.preview3d.grid(row=2, column=0, sticky="nsew")

    def _build_options(self) -> None:
        options = ttk.Frame(self, style="App.TFrame")
        options.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        ttk.Checkbutton(
            options,
            text="Yönü ters çevir",
            variable=self.reverse_var,
            command=self._on_option_change,
        ).pack(side="left")
        ttk.Checkbutton(
            options,
            text="3B yönelim (Z eğimini izle)",
            variable=self.use_3d_var,
            command=self._on_option_change,
        ).pack(side="left", padx=(14, 0))
        ttk.Label(options, text="Hedef eksen", style="Muted.TLabel").pack(
            side="left", padx=(16, 4)
        )
        self.axis_combo = ttk.Combobox(
            options,
            textvariable=self.axis_var,
            values=tuple(TARGET_AXES),
            state="readonly",
            width=7,
        )
        self.axis_combo.pack(side="left")
        self.axis_combo.bind("<<ComboboxSelected>>", self._on_axis_change)
        ttk.Label(
            options,
            text="normal bu yerel eksene hizalanır",
            style="Hint.TLabel",
        ).pack(side="left", padx=(6, 0))

        self.apply_button = ttk.Button(
            options, text="Uygula", style="Primary.TButton", command=self._apply
        )
        self.apply_button.pack(side="right")
        self.preview_button = ttk.Button(
            options, text="Önizle", style="Secondary.TButton", command=self._preview
        )
        self.preview_button.pack(side="right", padx=(0, 6))

    def _build_results(self) -> None:
        result_head = ttk.Frame(self, style="App.TFrame")
        result_head.grid(row=3, column=0, sticky="ew", pady=(2, 4))
        ttk.Label(result_head, text="Sonuç", style="Section.TLabel").pack(side="left")
        ttk.Label(result_head, textvariable=self.count_var, style="Muted.TLabel").pack(
            side="left", padx=(6, 0)
        )

        tree_frame = ttk.Frame(self, style="App.TFrame")
        tree_frame.grid(row=4, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        columns = (
            "order",
            "joint",
            "x",
            "y",
            "z",
            "tangent",
            "tangent3d",
            "normal",
            "a",
            "b",
            "c",
            "status",
        )
        headings = {
            "order": "Sıra",
            "joint": "Joint",
            "x": "X",
            "y": "Y",
            "z": "Z",
            "tangent": "Teğet XY",
            "tangent3d": "Teğet 3B",
            "normal": "Normal",
            "a": "A°",
            "b": "B°",
            "c": "C°",
            "status": "Durum / uyarı",
        }
        widths = {
            "order": 35,
            "joint": 55,
            "x": 65,
            "y": 65,
            "z": 55,
            "tangent": 95,
            "tangent3d": 110,
            "normal": 95,
            "a": 48,
            "b": 48,
            "c": 48,
            "status": 190,
        }
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse", height=7
        )
        for column in columns:
            self.tree.heading(column, text=headings[column])
            anchor = (
                "center"
                if column in {"order", "a", "b", "c"}
                else ("e" if column in {"x", "y", "z"} else "w")
            )
            self.tree.column(
                column,
                width=widths[column],
                minwidth=38,
                anchor=anchor,
                stretch=column == "status",
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_y = ttk.Scrollbar(
            tree_frame,
            orient="vertical",
            command=self._scroll_tree,
            style="Vertical.TScrollbar",
        )
        tree_y.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tree_y.set)
        self.tree_grid = _TreeGrid(tree_frame, self.tree, THEMES["light"]["border"])
        self.tree.bind("<Configure>", lambda _event: self._refresh_tree_grid(), add="+")
        self.tree.bind(
            "<ButtonRelease-1>", lambda _event: self._refresh_tree_grid(), add="+"
        )
        self.tree.bind(
            "<KeyRelease>", lambda _event: self._refresh_tree_grid(), add="+"
        )
        self.tree.bind(
            "<MouseWheel>", lambda _event: self._refresh_tree_grid(), add="+"
        )

        self._action_buttons = [
            self.selection_button,
            self.all_button,
            self.geometry_sort_button,
            self.sort_button,
            self.add_button,
            self.up_button,
            self.down_button,
            self.remove_button,
            self.reverse_button,
            self.clear_button,
            self.preview_button,
            self.apply_button,
            self.connect_button,
        ]

    def _build_status(self) -> None:
        self.status_label = ttk.Label(
            self,
            textvariable=self.status_var,
            style="Muted.TLabel",
            justify="left",
            wraplength=1100,
        )
        self.status_label.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.status_label.bind("<Configure>", self._on_status_configure)

    def _on_status_configure(self, event: tk.Event) -> None:
        self.status_label.configure(wraplength=max(300, event.width - 4))

    # ------------------------------------------------------------- sequence UI

    def _refresh_sequence(self, select: list[int] | None = None) -> None:
        tree = self.sequence_list
        tree.delete(*tree.get_children())
        for index, name in enumerate(self.joint_names):
            tree.insert("", "end", iid=str(index), values=(f"{index + 1:02d}", name))
        self.sequence_count_var.set(f"{len(self.joint_names)} joint")

        wanted = [
            str(index) for index in (select or []) if 0 <= index < len(self.joint_names)
        ]
        if wanted:
            tree.selection_set(wanted)
            tree.focus(wanted[-1])
            tree.see(wanted[-1])

    def _invalidate_plan(self) -> None:
        self.plan = None
        self._clear_tree()
        self.count_var.set("0 joint")
        self.preview3d.show_message("Sıra değişti. Yeni düzeni görmek için Önizle.")

    def _load_selection(self, silent_empty: bool = False) -> None:
        self._set_busy(True)
        try:
            names = self.service.get_selected_joint_names()
            if names:
                try:
                    self._store_catalog(self.service.get_joint_names())
                except Exception:
                    pass
        except Exception as exc:
            messagebox.showerror("Seçim okunamadı", str(exc), parent=self)
            return
        finally:
            self._set_busy(False)

        if not names:
            if silent_empty:
                self.status_var.set(
                    "SAP2000 bağlantısı kuruldu · seçili joint yok, "
                    "jointleri seçip Ctrl+I ile alın."
                )
                return
            messagebox.showinfo(
                "Seçim boş",
                "SAP2000'de seçili joint bulunamadı. Jointleri seçip tekrar deneyin.",
                parent=self,
            )
            return

        unique = list(dict.fromkeys(names))
        self.joint_names = unique
        self._after_import(len(unique), "SAP2000 seçiminden")

    def _load_all_joints(self) -> None:
        self._set_busy(True)
        try:
            names = self.service.get_joint_names()
        except Exception as exc:
            messagebox.showerror("Joint listesi okunamadı", str(exc), parent=self)
            return
        finally:
            self._set_busy(False)

        if not names:
            messagebox.showinfo(
                "Joint bulunamadı",
                "SAP2000 modelinde joint bulunamadı.",
                parent=self,
            )
            return

        unique = list(dict.fromkeys(names))
        self._store_catalog(unique)
        self.joint_names = unique
        self._after_import(len(unique), "modelden")

    def _after_import(self, count: int, source: str) -> None:
        self._refresh_sequence()
        self.conn_var.set("SAP2000 · bağlı")
        self._invalidate_plan()
        self._update_entry_hint()
        self.sequence_list.focus_set()
        self.status_var.set(
            f"{count} joint {source} alındı · Yola göre sırala ile otomatik dizin "
            "veya oklarla elle düzenleyin"
        )

    def _on_entry_focus(self, _event: tk.Event) -> None:
        if not self._catalog_loaded and self.conn_var.get().endswith("bağlı"):
            self._ensure_catalog()

    def _store_catalog(self, names: list[str]) -> None:
        self._catalog = sorted(dict.fromkeys(names), key=_natural_key)
        self._catalog_loaded = True
        self._update_entry_hint()

    def _ensure_catalog(self) -> None:
        try:
            names = self.service.get_joint_names()
        except Exception:
            self._catalog_loaded = True
            return
        self._store_catalog(names)

    def _last_token(self) -> str:
        text = self.joint_entry.get()
        parts = _ENTRY_SPLIT.split(text)
        return parts[-1] if parts else ""

    def _update_suggestions(self) -> bool:
        token = self._last_token().strip()
        if token:
            matches = [
                name for name in self._catalog if token.casefold() in name.casefold()
            ]
        else:
            matches = list(self._catalog)
        self.joint_entry.configure(values=tuple(matches[:80]))
        self._update_entry_hint(match_count=len(matches) if token else None)
        return bool(matches)

    def _update_entry_hint(self, match_count: int | None = None) -> None:
        if not self._catalog:
            self.entry_hint_var.set(
                "Joint önerileri için SAP2000 bağlantısı kurun; elle de yazabilirsiniz."
            )
        elif match_count is not None:
            self.entry_hint_var.set(
                f"{match_count} eşleşen joint · Enter ile listeye ekleyin."
            )
        else:
            self.entry_hint_var.set(
                "Yazdıkça modeldeki eşleşen jointler önerilir · Enter ile ekleyin."
            )

    def _on_entry_key(self, event: tk.Event) -> None:
        if event.keysym in {"Return", "Escape", "Up", "Down", "Tab"}:
            return
        self._entry_typed = self.joint_entry.get()
        has_matches = self._update_suggestions()
        if has_matches and self.joint_entry.get().strip():
            try:
                self.tk.call("ttk::combobox::Post", str(self.joint_entry))
            except tk.TclError:
                pass

    def _on_entry_selected(self, _event: tk.Event) -> None:
        # "1, 1" yazıp öneriden "10" seçilirse önceki parçayı koru.
        typed = self._entry_typed
        selected = self.joint_entry.get()
        match = list(_ENTRY_SPLIT.finditer(typed))
        if match and selected and match[-1].end() > 0:
            prefix = typed[: match[-1].end()]
            self.joint_entry.set(prefix + selected)
            self.joint_entry.icursor("end")
        self._entry_typed = self.joint_entry.get()
        self._update_suggestions()

    def _add_from_entry(self, _event: tk.Event | None = None) -> str:
        tokens = split_joint_tokens(self.joint_entry.get())
        if not tokens:
            self.status_var.set("Eklemek için bir joint adı yazın.")
            self.joint_entry.focus_set()
            return "break"

        added: list[str] = []
        duplicates: list[str] = []
        for name in tokens:
            if name in self.joint_names:
                duplicates.append(name)
            else:
                added.append(name)
                self.joint_names.append(name)

        self.joint_entry.delete(0, "end")
        self.joint_entry.configure(values=())
        self._entry_typed = ""
        if added:
            self._refresh_sequence(
                select=list(
                    range(len(self.joint_names) - len(added), len(self.joint_names))
                )
            )
            self._invalidate_plan()
        parts: list[str] = []
        if added:
            parts.append(
                f"{len(added)} joint eklendi · sırayı düzenleyip Önizle'ye basın"
            )
        if duplicates:
            parts.append(f"zaten listede: {', '.join(duplicates)}")
        if parts:
            self.status_var.set(" · ".join(parts))
        self.joint_entry.focus_set()
        return "break"

    def _selected_indexes(self) -> list[int]:
        selected: list[int] = []
        for item in self.sequence_list.selection():
            try:
                selected.append(int(item))
            except ValueError:
                continue
        return sorted(index for index in selected if index < len(self.joint_names))

    def _move_selected(self, direction: int) -> None:
        selected = self._selected_indexes()
        if not selected:
            self.status_var.set("Taşımak için listeden joint seçin.")
            return
        names = list(self.joint_names)
        if direction < 0:
            if selected[0] == 0:
                return
            for index in selected:
                names[index - 1], names[index] = names[index], names[index - 1]
            new_selection = [index - 1 for index in selected]
        else:
            if selected[-1] >= len(names) - 1:
                return
            for index in reversed(selected):
                names[index + 1], names[index] = names[index], names[index + 1]
            new_selection = [index + 1 for index in selected]
        self.joint_names = names
        self._refresh_sequence(select=new_selection)
        self._invalidate_plan()
        self.status_var.set("Sıra güncellendi · Önizle'ye basın")

    def _remove_selected(self) -> None:
        selected = self._selected_indexes()
        if not selected:
            self.status_var.set("Silmek için listeden joint seçin.")
            return
        selected_set = set(selected)
        self.joint_names = [
            name
            for index, name in enumerate(self.joint_names)
            if index not in selected_set
        ]
        self._refresh_sequence()
        self._invalidate_plan()
        self.status_var.set(f"{len(selected)} joint listeden çıkarıldı")

    def _reverse_sequence(self) -> None:
        if not self.joint_names:
            return
        self.joint_names.reverse()
        self._refresh_sequence()
        self._invalidate_plan()
        self.status_var.set("Joint sırası ters çevrildi")

    def _clear_sequence(self) -> None:
        if not self.joint_names:
            return
        self.joint_names = []
        self._refresh_sequence()
        self._invalidate_plan()
        self.status_var.set("Joint listesi temizlendi")

    def _sort_by_name(self) -> None:
        if not self.joint_names:
            return
        self.joint_names.sort(key=_natural_key)
        self._refresh_sequence()
        self._invalidate_plan()
        self.status_var.set("Joint listesi ada göre sıralandı")

    def _sort_by_geometry(self) -> None:
        if len(self.joint_names) < 2:
            self.status_var.set("Yola göre sıralamak için en az 2 joint gerekir.")
            return

        selected = self._selected_indexes()
        anchor = selected[0] if len(selected) == 1 else 0
        preferred_start = self.joint_names[anchor]
        self._set_busy(True)
        try:
            ordered = self.service.order_along_curve(
                self.joint_names,
                preferred_start=preferred_start,
            )
        except Exception as exc:
            messagebox.showerror("Sıralama hatası", str(exc), parent=self)
            return
        finally:
            self._set_busy(False)

        self.joint_names = ordered
        self._refresh_sequence(select=[0])
        self._invalidate_plan()
        self.status_var.set(
            f"{len(ordered)} joint yola göre sıralandı · başlangıç {ordered[0]} · "
            "yönü Ters çevir ile değiştirin"
        )

    def _reset_preview_view(self) -> None:
        self.preview3d.reset_view()

    # --------------------------------------------------------------- actions

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self._action_buttons:
            button.configure(state=state)
        self.axis_combo.configure(state="disabled" if busy else "readonly")
        self.joint_entry.configure(state="disabled" if busy else "normal")
        try:
            self.winfo_toplevel().configure(cursor="watch" if busy else "")
        except tk.TclError:
            pass
        self.update_idletasks()

    def _joint_input(self) -> str:
        return "\n".join(self.joint_names)

    def _axis_key(self) -> str:
        return TARGET_AXES.get(self.axis_var.get(), "x")

    def _on_option_change(self) -> None:
        if self.plan is not None:
            self._preview()

    def _on_axis_change(self, _event: tk.Event | None = None) -> None:
        self.status_var.set(
            f"Hedef eksen {_axis_label(self._axis_key())}: normal bu yerel eksene hizalanacak."
        )
        self._on_option_change()

    def _toggle_theme(self) -> None:
        self._apply_theme("dark" if self._theme_name == "light" else "light")

    def _show_info(self) -> None:
        existing = self._info_window
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_set()
                    return
            except tk.TclError:
                pass
        self._info_window = InfoWindow(
            self.winfo_toplevel(),
            THEMES[self._theme_name],
            _asset_path("tiger.png"),
            dark=self._theme_name == "dark",
        )

    def _sync_title_bar(self) -> None:
        apply_title_bar_theme(
            self.winfo_toplevel(),
            THEMES[self._theme_name],
            self._theme_name == "dark",
        )

    def _apply_theme(self, name: str) -> None:
        theme = THEMES.get(name, THEMES["light"])
        self._theme_name = name if name in THEMES else "light"
        self.theme_button.configure(
            text="Aydınlık tema" if self._theme_name == "dark" else "Karanlık tema"
        )

        root = self.winfo_toplevel()
        root.configure(bg=theme["bg"])
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = theme["bg"]
        panel = theme["panel"]
        style.configure("App.TFrame", background=bg)
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=theme["text"])
        style.configure(
            "Title.TLabel",
            background=bg,
            foreground=theme["text"],
            font=("Segoe UI", 13, "bold"),
        )
        style.configure(
            "Section.TLabel",
            background=bg,
            foreground=theme["text"],
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Badge.TLabel",
            background=theme["heading_bg"],
            foreground=theme["muted"],
            padding=(6, 1),
            font=("Segoe UI", 8, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=bg,
            foreground=theme["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Hint.TLabel",
            background=bg,
            foreground=theme["muted"],
            font=("Segoe UI", 8),
        )
        style.configure(
            "PanelTitle.TLabel",
            background=panel,
            foreground=theme["text"],
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "PanelMuted.TLabel",
            background=panel,
            foreground=theme["muted"],
            font=("Segoe UI", 8),
        )
        style.configure(
            "PanelHint.TLabel",
            background=panel,
            foreground=theme["muted"],
            font=("Segoe UI", 8),
        )
        style.configure(
            "TButton",
            background=panel,
            foreground=theme["text"],
            bordercolor=theme["button_border"],
            lightcolor=theme["button_border"],
            darkcolor=theme["button_border"],
            borderwidth=1,
            relief="solid",
            padding=(10, 5),
            font=("Segoe UI", 9),
        )
        style.map(
            "TButton",
            background=[
                ("pressed", theme["heading_bg"]),
                ("active", theme["button_hover"]),
                ("disabled", panel),
            ],
            foreground=[("disabled", theme["muted"])],
            bordercolor=[("active", theme["button_border"])],
        )
        style.configure(
            "Tool.TButton",
            background=panel,
            foreground=theme["text"],
            bordercolor=theme["button_border"],
            lightcolor=theme["button_border"],
            darkcolor=theme["button_border"],
            borderwidth=1,
            relief="solid",
            padding=(9, 4),
            font=("Segoe UI", 9),
        )
        style.map(
            "Tool.TButton",
            background=[
                ("pressed", theme["selection"]),
                ("active", theme["button_hover"]),
                ("disabled", panel),
            ],
            foreground=[("disabled", theme["muted"])],
            bordercolor=[("active", theme["accent"])],
        )
        style.configure(
            "Compact.TButton",
            background=panel,
            foreground=theme["text"],
            bordercolor=theme["button_border"],
            lightcolor=theme["button_border"],
            darkcolor=theme["button_border"],
            borderwidth=1,
            relief="solid",
            padding=(5, 3),
            font=("Segoe UI", 8),
        )
        style.map(
            "Compact.TButton",
            background=[
                ("pressed", theme["selection"]),
                ("active", theme["button_hover"]),
                ("disabled", panel),
            ],
            foreground=[("disabled", theme["muted"])],
            bordercolor=[("active", theme["accent"])],
        )
        style.configure(
            "AccentOutline.TButton",
            background=panel,
            foreground=theme["accent"],
            bordercolor=theme["accent"],
            lightcolor=theme["accent"],
            darkcolor=theme["accent"],
            borderwidth=1,
            relief="solid",
            padding=(9, 4),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "AccentOutline.TButton",
            background=[
                ("pressed", theme["accent_hover"]),
                ("active", theme["accent"]),
                ("disabled", panel),
            ],
            foreground=[
                ("active", theme["accent_text"]),
                ("pressed", theme["accent_text"]),
                ("disabled", theme["muted"]),
            ],
            bordercolor=[("disabled", theme["border"])],
        )
        style.configure(
            "Secondary.TButton",
            background=panel,
            foreground=theme["text"],
            bordercolor=theme["button_border"],
            lightcolor=theme["button_border"],
            darkcolor=theme["button_border"],
            borderwidth=1,
            relief="solid",
            padding=(14, 5),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("pressed", theme["heading_bg"]),
                ("active", theme["button_hover"]),
                ("disabled", panel),
            ],
            foreground=[("disabled", theme["muted"])],
            bordercolor=[("active", theme["accent"])],
        )
        style.configure(
            "Primary.TButton",
            background=theme["accent"],
            foreground=theme["accent_text"],
            bordercolor=theme["accent"],
            lightcolor=theme["accent"],
            darkcolor=theme["accent"],
            borderwidth=1,
            relief="solid",
            padding=(16, 5),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[
                ("pressed", theme["accent_hover"]),
                ("active", theme["accent_hover"]),
                ("disabled", theme["button_border"]),
            ],
            foreground=[("disabled", theme["muted"])],
        )
        style.configure(
            "TCheckbutton",
            background=bg,
            foreground=theme["text"],
            indicatorbackground=theme["input_bg"],
            indicatorforeground=theme["accent"],
            focuscolor=bg,
            font=("Segoe UI", 9),
        )
        style.map(
            "TCheckbutton",
            background=[("active", bg)],
            indicatorbackground=[
                ("selected", theme["accent"]),
                ("active", theme["input_bg"]),
            ],
            indicatorforeground=[("selected", theme["accent_text"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=theme["input_bg"],
            background=panel,
            foreground=theme["text"],
            arrowcolor=theme["muted"],
            bordercolor=theme["button_border"],
            lightcolor=theme["button_border"],
            darkcolor=theme["button_border"],
            borderwidth=1,
            padding=(6, 4),
            font=("Segoe UI", 9),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", theme["input_bg"])],
            background=[
                ("readonly", panel),
                ("active", theme["button_hover"]),
            ],
            foreground=[("readonly", theme["text"])],
            selectbackground=[("readonly", theme["input_bg"])],
            selectforeground=[("readonly", theme["text"])],
            bordercolor=[("focus", theme["accent"])],
        )
        style.configure(
            "Treeview",
            background=panel,
            fieldbackground=panel,
            foreground=theme["text"],
            bordercolor=theme["border"],
            borderwidth=0,
            relief="flat",
            rowheight=22,
            font=("Segoe UI", 9),
        )
        style.map(
            "Treeview",
            background=[("selected", theme["selection"])],
            foreground=[("selected", theme["selection_fg"])],
        )
        style.configure(
            "Treeview.Heading",
            background=theme["heading_bg"],
            foreground=theme["heading_fg"],
            bordercolor=theme["border"],
            relief="flat",
            padding=(6, 4),
            font=("Segoe UI", 8, "bold"),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", theme["heading_bg"])],
        )
        style.configure(
            "Sequence.Treeview",
            background=theme["input_bg"],
            fieldbackground=theme["input_bg"],
            foreground=theme["text"],
            bordercolor=theme["border"],
            borderwidth=0,
            relief="flat",
            rowheight=24,
            font=("Segoe UI", 9),
        )
        style.map(
            "Sequence.Treeview",
            background=[("selected", theme["accent"])],
            foreground=[("selected", theme["accent_text"])],
        )
        style.configure(
            "Sequence.Treeview.Heading",
            background=theme["heading_bg"],
            foreground=theme["heading_fg"],
            bordercolor=theme["border"],
            relief="flat",
            padding=(5, 3),
            font=("Segoe UI", 8, "bold"),
        )
        style.map(
            "Sequence.Treeview.Heading",
            background=[("active", theme["heading_bg"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=theme["button_bg"],
            troughcolor=bg,
            arrowcolor=theme["muted"],
            bordercolor=bg,
            lightcolor=theme["button_bg"],
            darkcolor=theme["button_bg"],
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", theme["button_hover"])],
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=theme["button_bg"],
            troughcolor=bg,
            arrowcolor=theme["muted"],
            bordercolor=bg,
            lightcolor=theme["button_bg"],
            darkcolor=theme["button_bg"],
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[("active", theme["button_hover"])],
        )

        for border in self._card_borders:
            border.configure(bg=theme["border"])
        self.sequence_border.configure(
            bg=theme["border"],
            highlightbackground=theme["button_border"],
            highlightcolor=theme["accent"],
        )
        self.preview3d.set_palette(theme)
        self.tree_grid.set_color(theme["border"])
        self.tree.tag_configure("warn", foreground=theme["warn"])
        self.tree.tag_configure("error", foreground=theme["error"])
        self.tree.tag_configure("ok", foreground=theme["ok"])

        for pattern, value in (
            ("*TCombobox*Listbox.background", theme["input_bg"]),
            ("*TCombobox*Listbox.foreground", theme["text"]),
            ("*TCombobox*Listbox.selectBackground", theme["accent"]),
            ("*TCombobox*Listbox.selectForeground", theme["accent_text"]),
        ):
            root.option_add(pattern, value)

        self.after_idle(self._sync_title_bar)

    def _test_connection(self) -> None:
        connected = False
        self._set_busy(True)
        try:
            self.service.test_connection()
            try:
                self._store_catalog(self.service.get_joint_names())
            except Exception:
                pass
        except Exception as exc:
            self.conn_var.set("SAP2000 · bağlantı yok")
            messagebox.showerror("SAP2000 bağlantı hatası", str(exc), parent=self)
        else:
            self.conn_var.set("SAP2000 · bağlı")
            self._update_entry_hint()
            self.status_var.set("SAP2000 bağlantısı kuruldu.")
            connected = True
        finally:
            self._set_busy(False)

        if connected and not self.joint_names:
            self._load_selection(silent_empty=True)
        elif connected:
            self.status_var.set(
                "SAP2000 bağlantısı kuruldu · mevcut liste korundu, "
                "seçimi yenilemek için Ctrl+I."
            )

    def _calculate_plan(self) -> AxisPlan:
        if not self.joint_names:
            raise ValueError("Joint listesi boş. En az 2 joint ekleyin.")
        plan = self.service.preview(
            self._joint_input(),
            reverse_normal=self.reverse_var.get(),
            target_axis=self._axis_key(),
            use_3d=self.use_3d_var.get(),
        )
        self.conn_var.set("SAP2000 · bağlı")
        return plan

    def _preview(self) -> None:
        self._set_busy(True)
        try:
            plan = self._calculate_plan()
        except Exception as exc:
            self.plan = None
            self._clear_tree()
            self.count_var.set("0 joint")
            self.preview3d.show_message("Hesaplama başarısız. Listeyi kontrol edin.")
            self.status_var.set("Hesaplama başarısız.")
            messagebox.showerror("Hesaplama hatası", str(exc), parent=self)
            return
        finally:
            self._set_busy(False)

        self.plan = plan
        self._render_plan(plan)

    def _apply(self) -> None:
        self._set_busy(True)
        try:
            plan = self._calculate_plan()
            self.plan = plan
            if plan.applicable_count == 0:
                messagebox.showerror(
                    "Uygulanabilir joint yok",
                    "Hiçbir joint için geçerli teğet/normal hesaplanamadı. "
                    "Joint listesini ve koordinatları kontrol edin.",
                    parent=self,
                )
                self.status_var.set("Uygulama yapılmadı: geçerli joint yok.")
                return
            direction = "ters çevrildi" if plan.flipped else "dışa doğru"
            mode = "3B yönelim" if plan.use_3d else "2B izdüşüm"
            confirmed = messagebox.askyesno(
                "Local axes uygula",
                f"{plan.applicable_count} joint · hedef {_axis_label(plan.target_axis)} · "
                f"yön {direction} · {mode}.\n\n"
                "A/B/C açıları SAP2000'e yazılacak. Devam edilsin mi?",
                parent=self,
            )
            if not confirmed:
                self.status_var.set("Uygulama kullanıcı tarafından iptal edildi.")
                return
            report = self.service.apply(plan)
        except Exception as exc:
            self.plan = None
            self._clear_tree()
            self.count_var.set("0 joint")
            self.preview3d.show_message("Uygulama başarısız. Bağlantıyı kontrol edin.")
            self.status_var.set("Uygulama başarısız.")
            messagebox.showerror("Uygulama hatası", str(exc), parent=self)
            return
        finally:
            self._set_busy(False)

        self._render_plan(plan, report)
        self._show_apply_result(report)

    def _render_plan(self, plan: AxisPlan, report: ApplyReport | None = None) -> None:
        self._clear_tree()
        self.count_var.set(f"{len(plan.results)} joint")
        self.preview3d.show_plan(plan)
        applied = set(report.applied) if report else set()
        failures = dict(report.failed) if report else {}

        for index, result in enumerate(plan.results, start=1):
            self._insert_result(index, result, applied, failures)

        direction = "ters" if plan.flipped else "dışa"
        mode = "3B yönelim" if plan.use_3d else "2B izdüşüm"
        if report:
            parts = [
                report.summary.rstrip("."),
                f"eksen {_axis_label(plan.target_axis)}",
                f"yön {direction}",
                mode,
                f"oy +{plan.positive_votes}/-{plan.negative_votes}",
            ]
            if report.refresh_warning:
                parts.append(f"yenileme: {report.refresh_warning}")
        else:
            parts = [
                f"{plan.applicable_count}/{len(plan.results)} joint hazır",
                f"eksen {_axis_label(plan.target_axis)}",
                f"yön {direction}",
                mode,
                f"oy +{plan.positive_votes}/-{plan.negative_votes}",
            ]
        parts.extend(plan.warnings)
        self.status_var.set("  |  ".join(parts))
        self.after_idle(self._refresh_tree_grid)

    def _insert_result(
        self,
        index: int,
        result: JointAxisResult,
        applied: set[str],
        failures: dict[str, str],
    ) -> None:
        name = result.joint.name
        messages = list(result.warnings)
        tag = "ok"
        if name in failures:
            messages.insert(0, failures[name])
            tag = "error"
            status = "Hata"
        elif name in applied:
            status = "Güncellendi"
        elif result.applicable:
            status = "Hazır"
        else:
            status = "Atlandı"
            tag = "error"

        if messages:
            status = f"{status}: {' '.join(messages)}"
            if tag == "ok":
                tag = "warn"

        angle_a, angle_b, angle_c = result.angles or (None, None, None)
        self.tree.insert(
            "",
            "end",
            values=(
                index,
                name,
                _fmt(result.joint.x),
                _fmt(result.joint.y),
                _fmt(result.joint.z),
                _fmt_vector(result.tangent),
                _fmt_vector3(result.tangent_3d),
                _fmt_vector(result.normal),
                _fmt_angle(angle_a),
                _fmt_angle(angle_b),
                _fmt_angle(angle_c),
                status,
            ),
            tags=(tag,),
        )

    def _clear_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._refresh_tree_grid()

    def _scroll_tree(self, *args: str) -> None:
        self.tree.yview(*args)
        self.after_idle(self._refresh_tree_grid)

    def _refresh_tree_grid(self) -> None:
        self.tree_grid.refresh()

    def _show_apply_result(self, report: ApplyReport) -> None:
        lines = [report.summary]
        if report.refresh_warning:
            lines.append(f"Görünüm yenileme uyarısı: {report.refresh_warning}")
        if report.failed:
            lines.append("")
            lines.append("Hatalı jointler:")
            for name, error in report.failed[:10]:
                lines.append(f"- {name}: {error}")
            if len(report.failed) > 10:
                lines.append(f"... ve {len(report.failed) - 10} joint daha.")
            messagebox.showwarning("Uygulama sonucu", "\n".join(lines), parent=self)
        else:
            messagebox.showinfo("Uygulama sonucu", "\n".join(lines), parent=self)


def _run_self_test() -> None:
    """Paketlenmiş exe içinde comtypes ve ikon varlığını doğrular."""

    import comtypes.client  # noqa: F401 - PyInstaller'ın paketlemesi için

    from .sap import SapConnection
    from .service import JointAxesService

    if not _asset_path("app.ico").exists():
        raise RuntimeError("app.ico paket içinde bulunamadı.")
    if not _asset_path("tiger.png").exists():
        raise RuntimeError("tiger.png paket içinde bulunamadı.")
    SapConnection()
    JointAxesService()


def main() -> None:
    if "--self-test" in sys.argv:
        _run_self_test()
        return

    _enable_dpi_awareness()
    root = tk.Tk()
    root.title(f"{APP_NAME} {APP_VERSION}")
    root.geometry("1140x760")
    root.minsize(1000, 680)
    _apply_window_icon(root)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    app = JointAxesWindow(root)
    root.update_idletasks()
    app._sync_title_bar()
    if "--smoke-test" in sys.argv:
        root.withdraw()
        app.update_idletasks()
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
