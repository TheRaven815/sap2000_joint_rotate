# SAP2000 2D/3D Joint Local Axes Alignment Tool

**Version:** v0.3.1 · **Developer:** Enes Eliağır · **Website:** [zadax.net](https://zadax.net)

A Windows desktop utility that updates the local axes of a sequence of SAP2000
joints in one operation. For every joint along the selected line, the tool
aligns a chosen local axis with the outward normal of the line while keeping
the remaining axes consistent with the geometry.

The default mode evaluates the geometry in the XY plane. The **3D orientation**
option makes the other local axes follow the vertical slope when the joint
line changes elevation.

The tool does not create or modify geometry. It only reads joint coordinates
from the active SAP2000 model and writes local-axis rotation angles through the
SAP2000 OAPI.

## Contents

- [Key features](#key-features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Running from source](#running-from-source)
- [Standalone Windows executable](#standalone-windows-executable)
- [Quick start](#quick-start)
- [Interface reference](#interface-reference)
- [Manual update check](#manual-update-check)
- [Algorithm](#algorithm)
- [Units and tolerances](#units-and-tolerances)
- [Error handling and warnings](#error-handling-and-warnings)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Version metadata](#version-metadata)
- [Limitations](#limitations)

## Key features

- Bulk update of joint local axes through the SAP2000 OAPI.
- 2D XY-plane mode and 3D orientation mode for lines with changing Z elevation.
- Automatic outward-normal selection using curvature voting.
- Manual direction reversal for straight lines, S-shaped lines, and ambiguous
  curvature cases.
- Target local axis selection: X (local 1), Y (local 2), or Z (local 3).
- Joint import from the current SAP2000 selection or from the entire model.
- Joint search and add suggestions while typing.
- Automatic line ordering with nearest-neighbor and 2-opt improvement.
- Natural name sorting (`2`, `10`, `100`).
- Interactive 3D preview with rotation, zoom, tangent vectors, normal vectors,
  and selected local-axis direction.
- Result table showing coordinates, tangents, normals, assigned `A/B/C`
  angles, and warnings.
- Light and dark themes, including Windows title-bar theming.
- Manual update check against GitHub Releases. No background checks and no
  automatic installation.

## Requirements

### Source installation

- Windows.
- Python 3.10 or newer.
- `comtypes` for the SAP2000 OAPI.
- SAP2000 installed, running, and with a model loaded.
- The SAP2000 model must be unlocked so local axes can be written.

### Packaged executable

- Windows.
- SAP2000 installed, running, and with a model loaded.
- Python is not required on the target machine.

Internet access is only needed when using the manual update check. Normal
alignment operations are local to SAP2000 and the application.

## Installation

Clone the repository and install the runtime dependency:

```powershell
git clone https://github.com/TheRaven815/sap2000_joint_rotate.git
cd sap2000_joint_rotate
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

For development and tests, install the editable package with the development
extras:

```powershell
pip install -e ".[dev]"
```

## Running from source

From the repository root:

```powershell
python -m joint_axes
```

Or:

```powershell
python run.py
```

With an editable installation, the console entry point is also available:

```powershell
sap2000-joint-axes
```

## Standalone Windows executable

The executable bundles Python, Tkinter, and `comtypes`. SAP2000 must still be
installed and running on the target machine.

Install the build requirements:

```powershell
pip install -r requirements-build.txt
```

Build the executable:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Alternatively, double-click `build_exe.bat` in Windows Explorer.

The output is:

```text
dist\SAP2000JointAxes.exe
```

The build script automatically uses `.venv\Scripts\python.exe` when a local
virtual environment exists. The application icon is loaded from
`joint_axes/assets/app.ico`; the window and taskbar icon use
`joint_axes/assets/tiger.png`.

## Quick start

1. Open SAP2000 and load the model. Make sure the model is unlocked.
2. In the tool, click **Bağlantıyı test et** (Test connection) to connect to the
   active SAP2000 instance. If the joint list is empty, the current SAP2000
   selection is imported automatically.
3. Use **Seçili jointleri al** (`Ctrl+I`, Import selected joints) to refresh the
   list from the current selection, or **Tümünü al** (`F5`, Import all) to load
   every joint in the model.
4. Review and edit the order in the **Joint sırası** (Joint sequence) panel.
   SAP2000 does not guarantee selection order, so use the ordering tools below
   before applying the axes.
5. Choose **Yönü ters çevir** (Reverse direction) when the automatically chosen
   outward side is not the desired side. This is especially useful for straight
   lines and S-shaped geometry.
6. Choose the local axis that should align with the outward normal:
   `X (1)`, `Y (2)`, or `Z (3)`.
7. Enable **3B yönelim (Z eğimini izle)** (3D orientation, follow Z slope) when
   the joint elevation changes along the line.
8. Click **Önizle** (Preview) to inspect tangents, normals, and `A/B/C` angles
   without writing anything to SAP2000. The 3D preview on the right shows the
   joint line, blue normal arrows, and the selected local-axis direction. In
   3D mode, green tangent arrows are also drawn.
9. Click **Uygula** (Apply) to assign the local axes. SAP2000 refreshes its view
   after the operation.

Preview is read-only. Nothing is written to SAP2000 until **Uygula** is pressed.

## Interface reference

### Header

- **Bağlantıyı test et** (Test connection): connects to the active SAP2000
  instance and reports the connection state.
- **Info**: opens the About window with version information, developer details,
  the zadax.net link, and the manual update check.
- **Karanlık tema / Aydınlık tema** (Dark theme / Light theme): switches the
  application theme. The Windows title bar follows the selected theme through
  DWM.

### Joint sequence panel

The sequence panel lists the order number and joint name in two columns.

- **Joint ara / ekle** (Search / add joint): typing filters the joints available
  in the connected model and shows matching suggestions.
- `Enter` or **Ekle** (Add): adds one joint or a comma-separated list of joints.
- **Yola göre sırala** (Order along path): orders the selected joints along the
  line using their coordinates. The implementation uses a nearest-neighbor
  construction followed by 2-opt improvement and is suitable for large joint
  sets (100+ joints). The starting endpoint is preserved; use **Ters çevir**
  (Reverse) when the direction should be changed.
- **Ada göre sırala** (Sort by name): applies natural sorting (`2`, `10`, `100`).
- **↑ Yukarı**, **↓ Aşağı**, **Sil**, **Ters çevir**, and **Temizle**: move up,
  move down, delete, reverse, and clear the sequence.

### 3D preview

- Drag to rotate the view.
- Use the mouse wheel to zoom.
- **Görünümü sıfırla** (Reset view) restores the initial camera angle.
- The preview displays the joint line, normal arrows, the selected local-axis
  direction, and 3D tangent arrows when 3D orientation is enabled.

### Options

- **Yönü ters çevir** (Reverse direction): flips the automatically selected
  outward normal by 180 degrees.
- **3B yönelim (Z eğimini izle)** (3D orientation): follows the full 3D tangent
  when Z elevation changes.
- **Hedef eksen** (Target axis): selects which local axis is aligned with the
  outward normal: X, Y, or Z.

### Results

The result table reports, for each joint:

- sequence number and joint name;
- X, Y, Z coordinates;
- XY and 3D tangent vectors;
- normal vector;
- assigned `A/B/C` angles;
- warnings or errors.

Rows and columns are separated by thin grid lines.

## Manual update check

Update checking is intentionally manual. The application does not check for
updates in the background and does not download or install updates.

1. Open **Info**.
2. Click **Güncelleme kontrol et** (Check for updates).
3. The application queries the latest published GitHub release for this
   repository.
4. If a newer semantic version is available, the release page can be opened in
   the default browser.
5. If the application is up to date, no published release exists yet, or the
   network request fails, the result is shown in the dialog.

The check reads only release metadata from GitHub. It does not send model data
or any other project information.

## Algorithm

### Input and validation

The tool accepts a user-ordered list of joint names separated by commas,
semicolons, spaces, or newlines. Bracketed lists such as `[1, 2, 3]` are also
accepted.

The following conditions are validated before calculation:

- at least two joints are required;
- every joint name must be present in the active SAP2000 model;
- the same joint may not appear more than once;
- joint coordinates must be readable.

### Tangent vector

For ordered points `P0 ... P(n-1)`, the 2D tangent is calculated in the XY
plane:

- first point: `T0 = P1 - P0` (forward difference);
- interior point: `Ti = P(i+1) - P(i-1)` (central difference);
- last point: `T(n-1) = P(n-1) - P(n-2)` (backward difference).

If the tangent length is smaller than `1e-6`, the point is treated as
coincident. The previous valid tangent is used first; if none exists, the next
valid tangent is used. A warning is recorded for that joint. If no valid tangent
exists at all, the joint is skipped.

### Normal vector

For a 2D tangent `T = (dx, dy)`, the default normal is:

```text
N = (dy, -dx)
```

The vector is normalized to unit length. The angle of the normal relative to
global X is:

```text
theta = atan2(Ny, Nx)
```

The angle is converted from radians to degrees and normalized to the interval
`(-180, 180]`.

### Outward direction

For each interior point, the chord midpoint and curvature vector are:

```text
Mi = (P(i-1) + P(i+1)) / 2
Ci = Pi - Mi
```

The sign of `N . Ci` is evaluated at every interior point. If the negative votes
outnumber the positive votes, all normals are multiplied by `-1` so they face
outward. Points with zero curvature do not participate in the vote, which keeps
the normal direction stable at straight segments and curve-to-line transitions.

If there is no curvature or the vote is tied, the default normal direction is
kept and a warning is shown. The **Yönü ters çevir** option flips the final
result by 180 degrees.

### 3D orientation

When **3B yönelim (Z eğimini izle)** is enabled, the 3D tangent is calculated
with the same forward/central/backward difference rules. The horizontal outward
normal `N` remains the target direction. A right-handed local frame is built
from the signed 3D tangent `T3` as follows:

| Target | Local 1 | Local 2 | Local 3 |
|---|---|---|---|
| X (1) | `N` | `T3` | `N x T3` |
| Y (2) | `-T3` | `N` | `(-T3) x N` |
| Z (3) | `T3 x N` | `T3` | `N` |

`T3` is oriented to follow the 2D tangent direction. When the Z coordinate
changes, the axes other than the target axis follow the slope. The frame is
converted to SAP2000 `A/B/C` angles using the SAP2000 Z-Y-X rotation order.

When all Z coordinates are equal, 3D mode produces the same angles as 2D mode.

### Target axis and SAP2000 assignment

SAP2000 defines joint local axes with the following rotation order:

1. rotate about the global 3 axis by `A`;
2. rotate about the resulting 2 axis by `B`;
3. rotate about the resulting 1 axis by `C`.

For a normal angle `theta`, the target mapping is:

| Target | Meaning | A | B | C |
|---|---|---|---|---|
| X (1) | Normal aligns with local 1 | `theta` | 0 | 0 |
| Y (2) | Normal aligns with local 2 | `theta - 90` | 0 | 0 |
| Z (3) | Normal aligns with local 3 | `theta` | 90 | 0 |

Each joint is assigned with:

```python
SapModel.PointObj.SetLocalAxes(name, A, B, C)
```

After all assignments, the SAP2000 view is refreshed with:

```python
SapModel.View.RefreshView(0, False)
```

## Units and tolerances

The calculations depend only on coordinate differences and `atan2` ratios, so
the resulting angles are independent of the active SAP2000 unit system
(kN-m, N-mm, and so on).

The coincidence tolerance is `1e-6` in model coordinate units. This is a safe
threshold for typical structural model scales. Extremely small or unusually
scaled models may require additional review.

## Error handling and warnings

- A missing joint or an unreadable coordinate stops the preview and reports the
  affected joint.
- At least two joints are required, and duplicate joint names are rejected.
- During application, a failed `SetLocalAxes` call is reported for that joint
  while the remaining joints continue to be processed.
- If the view refresh fails, successful axis assignments are preserved and a
  warning is shown.
- If the points are not in the XY plane, a Z-difference warning is shown and the
  default 2D calculation uses the XY projection.
- Coincident points produce a tangent warning. A joint with no usable tangent
  is skipped.
- If the outward direction is ambiguous (straight line or tied vote), the
  default normal is kept and a warning recommends the manual direction reversal
  option.

## Testing

Run the test suite from the repository root:

```powershell
python -m pytest
```

Run the linter:

```powershell
python -m ruff check .
```

The tests do not require SAP2000. A fake OAPI model is used to verify coordinate
reading, selection reading, local-axis assignment, view refresh, geometry,
ordering, preview, theme, and update-check behavior.

## Project structure

```text
joint_axes/
  assets/          # app.ico and tiger.png
  __init__.py      # package version
  __main__.py      # python -m joint_axes entry point
  errors.py        # application error types
  geometry.py      # tangent, normal, outward direction, angles
  info.py          # About window and manual update check UI
  inputs.py        # joint list parsing and validation
  meta.py          # application identity and version metadata
  models.py        # data structures and vector mathematics
  ordering.py      # nearest-neighbor and 2-opt line ordering
  preview3d.py     # 3D canvas projection and drawing
  sap.py           # SAP2000 OAPI connection and adapter
  service.py       # preview and apply workflow
  ui.py            # Tkinter user interface
  updates.py       # GitHub Releases update check
  window_theme.py  # Windows title-bar theming
tests/             # unit tests
build_exe.ps1      # single-file executable build script
build_exe.bat      # Windows wrapper for the build script
run.py             # repository-root launcher
```

## Version metadata

The current version is defined in the following files and should be kept in
sync when preparing a release:

- `joint_axes/meta.py` — displayed application version;
- `joint_axes/__init__.py` — package `__version__`;
- `pyproject.toml` — package version;
- `build_assets/version_info.txt` — Windows executable metadata.

## Limitations

- The default mode evaluates geometry in the XY plane. Use **3D orientation**
  when the joint elevation changes.
- In 3D mode, the target axis remains the horizontal outward normal; the other
  two axes follow the 3D tangent.
- Joint order is user-controlled. Automatic path ordering is a convenience, not
  a substitute for reviewing the sequence.
- In 2D mode with the X target, `B` and `C` are zero. The selected target axis
  determines which of `A`, `B`, and `C` are nonzero.
- SAP2000 does not guarantee the order of joints returned from a selection.
- The outward side cannot be determined automatically for a perfectly straight
  line or a tied curvature vote. Use **Yönü ters çevir** in those cases.
- The tool updates joint local axes only. Frame, shell, and other object local
  axes are outside its scope.
