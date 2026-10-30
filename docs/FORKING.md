# Building your own version

Fork this repository on GitHub, then clone your fork. The main source targets Item Compare 1.2.1 and Dawnwalker 1.1. The optional Custom Heading source is 1.0.1.

## Requirements

- Windows and Python 3.12 or later.
- [UAssetGUI](https://github.com/atenfyr/UAssetGUI) 1.1.0 and [retoc](https://github.com/trumank/retoc) 0.1.5, placed in `development/tools/` with their required dependencies.
- UAssetGUI portable configuration under `development/tools/Data/`.
- A matching Dawnwalker 1.1 `.usmap`, pristine extracted `.uasset`/`.uexp` files, and the installed game's `Content/Paks` directory, including `global.utoc` and `global.ucas`.

Obtain the tools from their upstream projects and follow their extraction and mapping guidance. This repository does not supply game files, mappings, decryption keys, or tool binaries. The extraction root must contain `Dawnwalker/Content/`, including UI dependencies. Do not mix game versions.

## Build

From the repository root in PowerShell, replace the example input paths:

```powershell
python development/prepare_patch11.py --mapping 'C:/inputs/Dawnwalker.usmap' --extracted-root 'C:/inputs/extracted' --game-paks 'C:/games/Dawnwalker/Content/Paks'
python development/build_mod.py
python development/verify_mod.py --game-paks 'C:/games/Dawnwalker/Content/Paks' --reference-root 'C:/inputs/extracted'
python development/package_mod.py
```

Preparation copies game inputs into the ignored `development/patch11-stock/` working directory and decodes the stock widgets. Supply any missing reference assets from the same game version. Explicit input arguments avoid any dependency on the author's Better Quickslots workspace.

The builder modifies the inventory, shop and storage widgets and creates private comparison tooltips. `storage_mod.py` and `localization_mod.py` provide the shared-screen and heading changes. Change `VERSION` in `build_mod.py` for your own release and prepare its `releases/ItemCompare-v<VERSION>/README.txt` and `CHANGELOG.txt` before packaging.

The packager requires a passing verification report for the exact payload. It copies the editable release documents verbatim and produces the three mod files plus those two documents in a ZIP. Keep the source license with source distributions; game and third-party assets retain their own rights.

## Verification

The verifier checks serialized assets, comparison control flow, layout contracts, localization, tooltip lifecycle and shared scrolling. Native game behavior is mocked, so test inventory, merchants, storage, both rings, long-description scrolling, repeated transfers, screen closing and reopening in the actual game before releasing a fork.

An optional historical 1.1.0 fixture reproduces a previous bug when available locally. It is excluded from source distribution; without it, the report marks that reproduction false while still running current lifecycle recovery checks.

## Custom Heading

The standalone UE4SS add-on source is in `addons/ItemCompareCustomHeading/`. Edit `Scripts/config.lua` for custom headings. The main mod does not require UE4SS.

To run the add-on's mocked Lua checks:

```powershell
python -m pip install lupa==2.8
python development/custom-heading/verify.py
```

These tests do not replace in-game testing with UE4SS. The historical add-on release audit and its packaging reports are local development artifacts and are not required to edit or use the Lua source.
