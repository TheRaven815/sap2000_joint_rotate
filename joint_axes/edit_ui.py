"""SAP2000 seçimini sabit bir çalışma UCS'sinde düzenleyen sekme."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from tkinter import messagebox, simpledialog, ttk

from .errors import InputValidationError, SapConnectionError
from .geometry import Point3
from .sap import is_disconnected
from .sap_edits import ModelContext, SapEdits, WorkingUcs
from .transform import NativeEdit, mirror, radial, translation

_THREE_D = "3B (noktalarla)"
_PARALLEL = tuple(f"{axis} eksenine paralel" for axis in "XYZ")
_OPERATIONS = ("Move", "Linear", "Radial", "Mirror")
_OBJECT_LABELS = {1: "Joint", 2: "Frame", 3: "Cable", 4: "Tendon", 5: "Area",
                  6: "Solid", 7: "Link"}
_VectorFields = tuple[tk.StringVar, tk.StringVar, tk.StringVar]


def _format_xyz(values: Point3) -> str:
    return " / ".join(f"{value:.7g}" for value in values)


def _number(value: tk.StringVar, label: str) -> float:
    try:
        return float(value.get().strip().replace(",", "."))
    except ValueError as exc:
        raise InputValidationError(f"{label} için geçerli bir sayı girin.") from exc


def _xyz(fields: _VectorFields, label: str) -> Point3:
    x, y, z = fields
    return _number(x, f"{label} X"), _number(y, f"{label} Y"), _number(z, f"{label} Z")


class EditTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, sap: SapEdits,
                 mark_connected: Callable[[], None], mark_disconnected: Callable[[], None]) -> None:
        super().__init__(parent, padding=10, style="App.TFrame")
        self.sap = sap
        self._mark_connected = mark_connected
        self._mark_disconnected = mark_disconnected
        self.ucs = WorkingUcs()
        self._busy = False
        self.active_var = tk.StringVar(self)
        self.basis_var = tk.StringVar(self)
        self.status = tk.StringVar(self, "SAP2000'de işlem yapılacak nesneleri seçin.")
        self.named_var = tk.StringVar(self)
        self.remove_var = tk.BooleanVar(self, False)
        self.mode_vars: dict[str, tk.StringVar] = {}
        self.count_vars: dict[str, tk.StringVar] = {}
        self.points: dict[str, list[_VectorFields]] = {}
        self._first_points: dict[str, tuple[ModelContext, Point3]] = {}
        self.angle_var = tk.StringVar(self, "90")
        self.columnconfigure(0, weight=1)
        self._build_reference()
        self._build_operations()
        self._build_actions()
        self._show_ucs()

    def _build_reference(self) -> None:
        box = ttk.LabelFrame(self, text="Çalışma koordinat sistemi", padding=(12, 8))
        box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        box.columnconfigure(0, weight=1)
        ttk.Label(box, textvariable=self.active_var, style="Section.TLabel").grid(sticky="w")
        ttk.Label(box, textvariable=self.basis_var, style="Muted.TLabel").grid(
            sticky="w", pady=(2, 6)
        )
        sources = ttk.Frame(box)
        sources.grid(sticky="ew")
        for text, action in (
            ("Global", lambda: self._set_ucs(WorkingUcs())),
            ("Seçili profilden al", lambda: self._set_ucs(self.sap.frame_ucs())),
            ("SAP2000 aktif UCS'yi al", self._use_current),
            ("UCS listesini yenile", self._load_systems),
        ):
            ttk.Button(sources, text=text, command=lambda fn=action: self._run(fn)).pack(
                side="left", padx=(0, 6)
            )
        self.named_combo = ttk.Combobox(sources, textvariable=self.named_var, width=21,
                                        state="disabled")
        self.named_combo.pack(side="left", fill="x", expand=True)
        self.named_combo.bind("<<ComboboxSelected>>", self._use_named)
        footer = ttk.Frame(box)
        footer.grid(sticky="ew", pady=(6, 0))
        ttk.Label(
            footer, text="Profilde orijin I ucu, X/Y/Z ise Local 1/2/3. Hedef seçimi UCS'yi değiştirmez.",
            style="Muted.TLabel",
        ).pack(side="left")
        ttk.Button(footer, text="SAP2000'de etkinleştir", style="Tool.TButton",
                   command=lambda: self._run(self._activate_in_sap)).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Bağlantı tanısı", style="Tool.TButton",
                   command=lambda: self._run(self._diagnose)).pack(side="right")

    def _diagnose(self) -> None:
        report = self.sap.diagnostics()
        self.status.set("Bağlantı tanısı tamamlandı; model değiştirilmedi.")
        if messagebox.askyesno("SAP2000 bağlantı tanısı", report, parent=self,
                               detail="Tanı metni panoya kopyalansın mı?"):
            self.clipboard_clear()
            self.clipboard_append(report)

    def _build_operations(self) -> None:
        self.operations = ttk.Notebook(self)
        self.operations.grid(row=1, column=0, sticky="ew")
        self.operations.enable_traversal()
        for kind in _OPERATIONS:
            panel = ttk.Frame(self.operations, padding=(14, 10))
            self.operations.add(panel, text=kind)
            self.points[kind] = []
            if kind in {"Move", "Linear"}:
                self._build_translation(panel, kind)
            else:
                self._build_points(panel, kind)
        self.operations.bind("<<NotebookTabChanged>>", self._operation_changed)

    def _build_translation(self, panel: ttk.Frame, kind: str) -> None:
        ttk.Label(panel, text="Yerel öteleme" if kind == "Move" else "Kopyalar arası yerel artış",
                  style="Section.TLabel").grid(row=0, column=0, columnspan=5, sticky="w")
        self._vector_row(panel, 2, kind, "Δ", ("ΔX", "ΔY", "ΔZ"), ("0", "0", "0"))
        ttk.Button(panel, text="1. jointi al", command=lambda: self._run(
            lambda: self._pick_delta(kind, first=True))).grid(row=2, column=4, padx=(4, 0))
        ttk.Button(panel, text="2. jointi al ve Δ hesapla", command=lambda: self._run(
            lambda: self._pick_delta(kind, first=False))).grid(row=2, column=5, padx=(6, 0))
        if kind == "Linear":
            self._scalar(panel, 3, "Kopya sayısı", self._count_field(kind))

    def _build_points(self, panel: ttk.Frame, kind: str) -> None:
        is_radial = kind == "Radial"
        mode = tk.StringVar(self, _PARALLEL[2] if is_radial else _THREE_D)
        self.mode_vars[kind] = mode
        ttk.Label(panel, text="Dönme ekseni" if is_radial else "Ayna düzlemi").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        combo = ttk.Combobox(panel, textvariable=mode, values=(*_PARALLEL, _THREE_D),
                             state="readonly", width=22)
        combo.grid(row=0, column=1, columnspan=3, sticky="w", pady=(0, 4))
        entries = []
        for index, initial in enumerate((("0", "0", "0"), ("1", "0", "0"), ("0", "1", "0"))):
            if is_radial and index == 2:
                break
            entries.append(self._vector_row(panel, index + 2, kind, f"Nokta {index+1}",
                                           ("X", "Y", "Z"), initial))
            ttk.Button(panel, text="Seçili jointi al", command=lambda i=index: self._run(
                lambda: self._pick_point(kind, i))).grid(row=index+2, column=4, padx=(4, 0))
        tips = tk.StringVar(self)
        ttk.Label(panel, textvariable=tips, style="Muted.TLabel").grid(
            row=5, column=0, columnspan=6, sticky="w", pady=(4, 4)
        )

        def update(_event: tk.Event | None = None) -> None:
            axis = self._parallel_axis(kind)
            for row_index, row in enumerate(entries):
                for j, widget in enumerate(row):
                    ignored = axis is not None and (j == axis or row_index >= (1 if is_radial else 2))
                    widget.state(["disabled" if ignored else "!disabled"])
            for child in panel.grid_slaves(column=4):
                row_index = int(child.grid_info()["row"]) - 2
                ignored = axis is not None and row_index >= (1 if is_radial else 2)
                child.state(["disabled" if ignored else "!disabled"])
            if axis is None:
                tips.set("İki yerel nokta ekseni tanımlar." if is_radial else
                         "Bir doğru üzerinde olmayan üç yerel nokta düzlemi tanımlar.")
            else:
                plane = "".join(c for j, c in enumerate("XYZ") if j != axis)
                tips.set(f"Nokta 1, eksenin yerel {plane} düzlemiyle kesişimi." if is_radial else
                         f"Nokta 1 ve 2, aynanın yerel {plane} düzlemiyle kesişim doğrusunu tanımlar.")

        combo.bind("<<ComboboxSelected>>", update)
        update()
        if is_radial:
            self._scalar(panel, 6, "Açı artışı (°)", self.angle_var)
            self._scalar(panel, 7, "Kopya sayısı", self._count_field(kind))

    def _vector_row(self, panel: ttk.Frame, row: int, kind: str, label: str,
                    headers: tuple[str, str, str], initial: tuple[str, str, str]) -> list[ttk.Entry]:
        if row == 2:
            for col, name in enumerate(headers, 1):
                ttk.Label(panel, text=name, style="Muted.TLabel").grid(row=1, column=col, sticky="w")
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8))
        a, b, c = initial
        fields = tk.StringVar(self, a), tk.StringVar(self, b), tk.StringVar(self, c)
        self.points[kind].append(fields)
        entries = []
        for col, value in enumerate(fields, 1):
            entry = ttk.Entry(panel, textvariable=value, width=12)
            entry.grid(row=row, column=col, padx=(0, 6), pady=2, sticky="ew")
            entries.append(entry)
        return entries

    def _count_field(self, kind: str) -> tk.StringVar:
        self.count_vars[kind] = tk.StringVar(self, "1")
        return self.count_vars[kind]

    @staticmethod
    def _scalar(panel: ttk.Frame, row: int, label: str, value: tk.StringVar) -> None:
        ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(panel, textvariable=value, width=12).grid(row=row, column=1, sticky="w", padx=(0, 6))

    def _build_actions(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=2, column=0, sticky="ew", pady=(8, 4))
        self.remove_check = ttk.Checkbutton(bar, text="Orijinal nesneleri sil", variable=self.remove_var)
        self.remove_check.pack(side="left")
        self.apply_button = ttk.Button(bar, style="Primary.TButton", text="Taşı",
                                       command=lambda: self._run(lambda: self._submit(apply=True)))
        self.apply_button.pack(side="right")
        self.preview_button = ttk.Button(bar, text="Önizle",
                                         command=lambda: self._run(lambda: self._submit(apply=False)))
        self.preview_button.pack(side="right", padx=(0, 6))
        ttk.Label(
            self, text="Uzunluklar SAP2000'in aktif birimindedir. Kopyalamayı SAP2000'in yerel Replicate komutu yapar.",
            style="Muted.TLabel",
        ).grid(row=3, column=0, sticky="w")
        status = ttk.Label(self, textvariable=self.status, style="Muted.TLabel", justify="left")
        status.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        status.bind("<Configure>", lambda e: status.configure(wraplength=max(200, e.width)))
        self._operation_changed()

    def _operation_changed(self, _event: tk.Event | None = None) -> None:
        moving = self._kind() == "Move"
        if moving:
            self.remove_check.state(["disabled"])
        else:
            self.remove_check.state(["!disabled"])
        self.remove_var.set(False)
        self.apply_button.configure(text="Taşı" if moving else "Kopyala")

    def _kind(self) -> str:
        return _OPERATIONS[self.operations.index("current")]

    def _show_ucs(self) -> None:
        self.active_var.set(f"Aktif UCS: {self.ucs.label}")
        system = self.ucs.system
        x, y, z = zip(*system.matrix, strict=True)
        origin_unit = self.ucs.captured_in.length_unit if self.ucs.captured_in else ""
        self.basis_var.set(f"Global orijin ({_format_xyz(system.origin)}) {origin_unit}   ·   "
                           f"X ({_format_xyz(x)})   Y ({_format_xyz(y)})   Z ({_format_xyz(z)})")

    def _set_ucs(self, ucs: WorkingUcs) -> None:
        self.ucs = ucs
        self._first_points.clear()
        self._show_ucs()
        if ucs.captured_in is not None:
            self._mark_connected()
        self.status.set("Aktif UCS değişti. Hedef nesneleri seçip işlem parametrelerini kontrol edin.")

    def _load_systems(self) -> None:
        names = tuple(sorted(self.sap.coordinate_system_names(), key=str.casefold))
        self._mark_connected()
        self.named_combo.configure(values=names, state="readonly" if names else "disabled")
        self.named_var.set("")
        self.status.set("Listeden bir UCS seçin." if names else "Modelde kayıtlı kullanıcı UCS'si yok.")
        if names:
            self.named_combo.focus_set()

    def _use_named(self, _event: tk.Event) -> None:
        self._run(lambda: self._set_ucs(self.sap.named_ucs(self.named_var.get())))

    def _use_current(self) -> None:
        self._set_ucs(self.sap.named_ucs(self.sap.current_coordinate_system()))
        self._mark_connected()

    def _activate_in_sap(self) -> None:
        context = self.sap.context()
        self.ucs.in_context(context)
        name = None
        if self.ucs.sap_name is None:
            name = simpledialog.askstring(
                "SAP2000'de yeni UCS",
                "Profil eksenlerini SAP2000'de etkinleştirmek modele yeni bir UCS tanımı ekler.\n"
                "Geometri ve atamalar değişmez. Yeni UCS adı:",
                initialvalue="JointAxes_Frame", parent=self.winfo_toplevel(),
            )
            if name is None:
                return
        name, report = self.sap.activate_in_sap(self.ucs, context, name)
        self.ucs = replace(self.ucs, sap_name=name)
        self._mark_connected()
        self.status.set(f"SAP2000 aktif koordinat sistemi: {name}. Çalışma UCS'si sabit.")
        self._show_warnings(report.warnings, report.connection_lost)

    def _run(self, action: Callable[[], None]) -> None:
        if self._busy:
            return
        self._busy = True
        self.winfo_toplevel().configure(cursor="watch")
        self.update_idletasks()
        try:
            action()
        except Exception as exc:
            detail = str(exc)
            if is_disconnected(exc):
                self._mark_disconnected()
                detail += "\n\nSAP2000 yanıt vermiyor. Modeli yeniden açıp Bağlantıyı test et düğmesini kullanın."
            elif isinstance(exc, SapConnectionError):
                self._mark_disconnected()
            self.status.set(detail)
            messagebox.showerror("Move / Replicate", detail, parent=self)
        finally:
            self.winfo_toplevel().configure(cursor="")
            self._busy = False

    def _picked_local(self) -> tuple[ModelContext, Point3]:
        context = self.sap.context()
        system = self.ucs.in_context(context)
        point = system.local_point(self.sap.selected_joint(context))
        self._mark_connected()
        return context, point

    @staticmethod
    def _fill(fields: _VectorFields, xyz: Point3) -> None:
        for var, value in zip(fields, xyz, strict=True):
            var.set(f"{value:.16g}")

    def _pick_point(self, kind: str, index: int) -> None:
        context, point = self._picked_local()
        self._fill(self.points[kind][index], point)
        self.status.set(f"Nokta {index+1} alındı ({context.length_unit}). İşlemden önce hedefleri seçin.")

    def _pick_delta(self, kind: str, *, first: bool) -> None:
        context, point = self._picked_local()
        if first:
            self._first_points[kind] = (context, point)
            self.status.set("İlk joint alındı. SAP2000'de ikinci jointi tek başına seçin.")
            return
        start = self._first_points.get(kind)
        if start is None or start[0] != context:
            raise InputValidationError("Önce aynı model ve birimde 1. jointi alın.")
        x, y, z = point
        a, b, c = start[1]
        self._fill(self.points[kind][0], (x - a, y - b, z - c))
        self._first_points.pop(kind)
        self.status.set(f"Yerel Δ hesaplandı ({context.length_unit}). İşlemden önce hedefleri seçin.")

    def _parallel_axis(self, kind: str) -> int | None:
        mode = self.mode_vars[kind].get()
        return _PARALLEL.index(mode) if mode in _PARALLEL else None

    def _copies(self, kind: str) -> int:
        try:
            return int(self.count_vars[kind].get())
        except ValueError as exc:
            raise InputValidationError("Kopya sayısı pozitif bir tam sayı olmalı.") from exc

    def _prepare(self, context: ModelContext, kind: str) -> NativeEdit:
        ucs = self.ucs.in_context(context)
        remove = kind != "Move" and self.remove_var.get()
        fields = self.points[kind]
        if kind in {"Move", "Linear"}:
            copies = self._copies(kind) if kind == "Linear" else None
            return translation(ucs, _xyz(fields[0], "Δ"), copies, remove)

        axis = self._parallel_axis(kind)

        def point(index: int) -> Point3:
            x, y, z = (0.0 if j == axis else _number(var, f"Nokta {index+1} {'XYZ'[j]}")
                       for j, var in enumerate(fields[index]))
            return x, y, z

        first = point(0)
        if axis is None:
            second = point(1)
        else:
            x, y, z = (value + float(j == axis) for j, value in enumerate(first))
            second = (x, y, z)
        if kind == "Radial":
            return radial(ucs, first, second, _number(self.angle_var, "Açı"), self._copies(kind), remove)
        if axis is None:
            return mirror(ucs, first, second, point(2), remove)
        return mirror(ucs, first, point(1), second, remove)

    def _submit(self, *, apply: bool) -> None:
        kind = self._kind()
        context = self.sap.context()
        selection = self.sap.selection()
        if not selection:
            raise InputValidationError("SAP2000'de işlem yapılacak nesneleri seçin.")
        edit = self._prepare(context, kind)
        self._mark_connected()
        detail = self._summary(kind, edit, selection, context.length_unit)
        if not apply:
            messagebox.showinfo("Önizleme · SAP2000'e yazılmadı", detail, parent=self)
            return
        if not messagebox.askokcancel(
            "Model değişikliği" if not edit.remove else "Orijinal nesneleri silerek kopyala",
            detail + "\n\nBu işlem aktif SAP2000 modelini değiştirir. Uygulansın mı?",
            icon="warning" if edit.remove else "question", default="cancel", parent=self,
        ):
            return
        report = self.sap.apply(edit, context, selection)
        if report.created is None:
            result = f"Move tamamlandı · {len(selection)} seçili nesne."
        else:
            result = f"{kind} tamamlandı · SAP2000'in bildirdiği yeni nesne sayısı: {report.created}."
        self.status.set(result)
        self._show_warnings(report.warnings, report.connection_lost)

    def _show_warnings(self, warnings: tuple[str, ...], connection_lost: bool) -> None:
        if connection_lost:
            self._mark_disconnected()
            self.status.set(self.status.get() + " SAP2000 bağlantısı kesildi.")
        if warnings:
            messagebox.showwarning("İşlem tamamlandı, uyarı var", "\n".join(warnings), parent=self)

    def _summary(self, kind: str, edit: NativeEdit,
                 selection: tuple[tuple[int, str], ...], unit: str) -> str:
        targets = ", ".join(f"{_OBJECT_LABELS.get(code, 'Nesne')} {name}"
                            for code, name in selection[:5])
        if len(selection) > 5:
            targets += f" (+{len(selection) - 5})"
        lines = [f"{kind} · {len(selection)} seçili nesne", f"Hedef: {targets}",
                 f"Aktif UCS: {self.ucs.label}"]
        args = edit.args
        if kind in {"Move", "Linear"}:
            lines.append(f"Global Δ ({unit}): {_format_xyz(args[:3])}")
            if kind == "Linear":
                lines.append(f"Kopya sayısı: {args[3]}")
        else:
            n = 2 if kind == "Radial" else 3
            lines.extend(f"Global nokta {i+1} ({unit}): {_format_xyz(args[1+3*i:4+3*i])}"
                         for i in range(n))
            if kind == "Radial":
                lines.append(f"Açı artışı: {args[8]:g}° · Kopya sayısı: {args[7]}")
        if kind != "Move":
            lines.append("DİKKAT: Orijinal nesneler silinecek." if edit.remove else
                         "Orijinal nesneler silinmeyecek.")
        return "\n".join(lines)
