Item Compare Custom Heading - v1.0.1

An optional add-on for Item Compare in The Blood of Dawnwalker.
Choose your own text for the EQUIPPED heading in inventory, shops, and storage.

REQUIREMENTS
Item Compare and a working UE4SS installation compatible with Dawnwalker.
UE4SS is required only for this add-on. Item Compare still works on its own.
Neither Item Compare nor UE4SS is included in this download.
When the loader lacks FText(), the add-on tries Unreal's text conversion.
The loader must still support passing text to widget functions.

INSTALL
Close the game. Copy the ItemCompareCustomHeading folder into your existing
UE4SS Mods folder, normally:
<game folder>\Dawnwalker\Binaries\Win64\ue4ss\Mods

The result should include:
Mods\ItemCompareCustomHeading\enabled.txt
Mods\ItemCompareCustomHeading\Scripts\main.lua
Mods\ItemCompareCustomHeading\Scripts\config.lua

Keep your main Item Compare files installed in Paks\~mods.

CHOOSE YOUR HEADING
Open ItemCompareCustomHeading\Scripts\config.lua in a text editor.
Replace the text between the quotes. For example, change:

    Text = "EQUIPPED",

to:

    Text = "WYPOSAŻONO",

Save as UTF-8 and restart the game. More examples are included in config.lua.
The default remains EQUIPPED until you edit it. There is no in-game setting.

Your custom heading overrides automatic language selection, including when
using a fan translation. Keep it short and on one line. Letters and symbols
must be supported by your installed game font.

COMPATIBILITY / UPDATES
Designed for Item Compare 1.0.0 through 1.2.0. Shop and storage comparisons
require Item Compare 1.1.0 or later. The add-on has its own version number;
it does not need a matching download for each compatible main-mod update.

When updating Item Compare, leave this add-on installed. When updating this
add-on, keep a copy of your edited config.lua. Future game or mod changes
may require an add-on update.

UNINSTALL
Close the game and remove only the ItemCompareCustomHeading folder.
Restart to restore Item Compare's normal heading behavior.
Keep Item Compare, Better Quickslots, and other mods installed.
