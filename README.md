# Item Compare

A UI mod for The Blood of Dawnwalker that displays equipped gear beside the inventory, shop, or storage item being hovered or focused.

[![Item Compare showing a hovered weapon beside its equipped counterpart](promo/Screenshot%202026-09-09%20160528.png)](https://www.nexusmods.com/thebloodofdawnwalker/mods/373)

**v1.2.1 updates Item Compare for Dawnwalker 1.1.** The comparison cards have one heading above the stack. Compatible with Better Quickslots.

- Weapons, armor/clothing, rings, and amulets use the game's matching equipment slots.
- Equipped items appear in stock tooltips on the right in inventory, and on the left in shops and storage, with one shared **EQUIPPED** label above the stack.
- The heading follows the game's text language in Simplified Chinese, Spanish, Brazilian Portuguese, German, Japanese, Polish, Korean, and Russian, with English for other languages.
- Shop and storage comparisons apply only to merchant stock and stored items. Your character's items keep a single tooltip on those screens.
- Both equipped rings appear in a vertical stack, centered against the hovered tooltip.
- Empty slots are omitted. Items without equipment slots keep the original single tooltip.
- Hovering an already-equipped item shows only its own tooltip, including either equipped ring.
- The hovered tooltip retains the game's stat differences and ring comparison control.
- Equipment is read using the game's stock inventory functions. No items or saves are changed.
- UE4SS is not required.

## Install

Use the packaged Item Compare download from Nexus Mods. This repository contains source for building your own version. Close the game and copy the three mod files from the ZIP into:

`<game folder>\Dawnwalker\Content\Paks\~mods`

Create `~mods` if needed. The three files are:

```text
00000000_ItemCompare_P.pak
00000000_ItemCompare_P.ucas
00000000_ItemCompare_P.utoc
```

When upgrading, replace all three ItemCompare files together. Leave the Better Quickslots files as they are.

The ZIP includes a README and changelog; those documents do not need to be installed. Manual installation is supported. Mod-manager deployment has not been tested.

For your own heading text, install the optional [Custom Heading add-on](addons/ItemCompareCustomHeading/Scripts/config.lua) alongside Item Compare and edit its `Scripts/config.lua`. It supports custom translations regardless of the game's selected language. Only the add-on requires UE4SS; the main mod still works on its own. Keep the add-on installed when updating compatible main-mod versions.

To uninstall, close the game and remove only those three files. Keep other mods and UE4SS installed.

## Compatibility and testing

Requires Dawnwalker 1.1. Game updates may require an update to the mod. Other mods replacing `WBP_InventoryPanel`, `WBP_DoubleInventoryBase`, or `WBP_Shop_New` may conflict. Better Quickslots is compatible and optional.

The comparison stack is positioned relative to the existing tooltip, using its UI scale. Very tall descriptions, unusual aspect ratios, and modified UI scaling need an in-game visibility check. This version does not clamp the comparison stack to the screen edges.

## Source and forks

You're welcome to fork this project and make your own versions. The original code is available under the [MIT license](LICENSE); keep the copyright and license notice in your copies.

See [building your own version](docs/FORKING.md). Game assets, mappings, and third-party tools are not included or covered by this license. Supply your own legally obtained game files.
