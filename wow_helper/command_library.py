"""Hand-authored command reference. Strings are copied, never executed here."""

from dataclasses import dataclass
import unicodedata

GRAPHICS_SOURCE = "https://www.reddit.com/r/wowforever/comments/1x3hbv4/wow_forever_beyond_ultra_graphics_settings/"
GRASS_SOURCE = "https://www.reddit.com/r/wowforever/comments/1x2srnz/a_couple_of_commands_to_increase_the_amount_of/"
FLICKER_SOURCE = "https://www.reddit.com/r/wowforever/comments/1xoj9cy/insane_texture_flickering/"
ADDON_SOURCE = "https://www.curseforge.com/wow/addons/junk-and-repair-manager"
REVIEWED = "2026-11-20"
EXPERIMENT = ("Experimental value, not a verified maximum. The client may clamp or ignore it. "
              "Record your current value, change one setting, then compare the same scene and frame rate.")


@dataclass(frozen=True)
class Command:
    key: str
    title: str
    category: str
    command: str
    description: str
    status: str
    caution: str
    source: str
    variable: str = ""

    @property
    def inspect(self):
        return f'/dump GetCVar("{self.variable}")' if self.variable else ""

    @property
    def restore(self):
        if not self.variable or not self.command.startswith("/console "):
            return ""
        return f'/run SetCVar("{self.variable}", GetCVarDefault("{self.variable}"))'


def _setting(variable, value, title, category, description, *, status="Experimental",
             caution=EXPERIMENT, source=GRAPHICS_SOURCE):
    return Command(variable, title, category, f"/console {variable} {value}", description,
                   status, caution, source, variable)


def _wiki(variable):
    return "https://warcraft.wiki.gg/wiki/CVar_" + variable


COMMANDS = (
    _setting("ResampleSharpness", "-1", "Fix ground brightness flicker", "Fixes",
             "Disable FSR sharpening. Reported to fix the ground getting brighter while moving "
             "and darker when stopping. Also searchable as shimmer or texture flicker.",
             status="Reported fix", source=FLICKER_SOURCE,
             caution="A player confirmed this fix; it is not a diagnosis for every system. "
                     "0 means maximum sharpening, not off. Keep -1 if sharpening caused the problem."),
    _setting("farclip", "24000", "Far sight distance", "Draw distance",
             "Adjust the far clipping distance. A larger number is not proof of a larger rendered view."),
    _setting("horizonClip", "10000", "Distant horizon", "Draw distance",
             "Adjust where the distant horizon ends."),
    _setting("entityLodDist", "1000", "Distant entity detail", "Draw distance",
             "Adjust how far entities retain detail. Level of detail (LOD) differs from visibility."),
    _setting("doodadLodScale", "150", "Environmental prop detail", "Draw distance",
             "Adjust detail scaling for scenery props such as rocks and small objects."),
    Command("terrainLodDist", "Inspect terrain detail distance", "Draw distance",
            '/dump GetCVar("terrainLodDist")', "Inspect terrain level of detail distance.",
            "Inspect only", "No tested tuning value is included. Presence does not establish a live maximum.",
            _wiki("terrainLodDist"), "terrainLodDist"),
    Command("wmoLodDist", "Inspect world-object detail distance", "Draw distance",
            '/dump GetCVar("wmoLodDist")', "Inspect level of detail distance for world objects and structures.",
            "Inspect only", "No tested tuning value is included. Presence does not establish a live maximum.",
            _wiki("wmoLodDist"), "wmoLodDist"),
    _setting("groundEffectDensity", "128", "Denser grass", "Foliage",
             "Increase grass and ground clutter. 128 is a starting experiment; 256 is a denser alternative.",
             source=GRASS_SOURCE, caution=EXPERIMENT + " Dense grass can obscure quest objects and gathering nodes."),
    _setting("groundEffectDist", "500", "Grass draw distance", "Foliage",
             "Adjust how far away ground clutter is drawn.", source=GRASS_SOURCE),
    _setting("groundEffectFade", "370", "Grass fading distance", "Foliage",
             "Adjust ground-clutter fading. Compare with the draw-distance setting.", source=GRASS_SOURCE),
    _setting("shadowNumCascades", "4", "Shadow cascades", "Lighting",
             "Use four shadow cascades. The documented range is 1 to 4.", source=_wiki("shadowNumCascades")),
    _setting("shadowSoft", "1", "Soft shadows", "Lighting",
             "Enable soft shadows. The graphics preset may already enable this.", source=_wiki("shadowSoft")),
    _setting("shadowMode", "3", "Shadow quality", "Lighting",
             "Try shadow quality 3. Do not assume values above the documented 0 to 3 range improve it.",
             source=_wiki("shadowMode")),
    _setting("volumeFogLevel", "3", "Volumetric fog quality", "Lighting",
             "Try volumetric fog level 3, the top of the documented 0 to 3 range.", source=_wiki("volumeFogLevel")),
    _setting("bodyQuota", "200", "Rendered body limit", "Detail",
             "Raise the limit for component-based bodies rendered at once; busy areas may become more demanding."),
    _setting("ffxGlow", "0", "Disable full-screen glow", "Lighting",
             "Turn off the full-screen glow effect for a different visual appearance.", source=_wiki("ffxGlow")),
    _setting("bloomEnable", "1", "Enable bloom", "Lighting",
             "Enable bloom around bright areas; appearance is a preference.", source=_wiki("bloomEnable")),
    _setting("bloomUserMult", "0.5", "Bloom intensity", "Lighting",
             "Try a lower bloom intensity multiplier.", source=_wiki("bloomUserMult")),
    _setting("HDROutput", "1", "HDR output", "HDR",
             "Enable HDR output when the monitor and rendering configuration support it.",
             caution=EXPERIMENT + " Use only with a working HDR display configuration."),
    _setting("HDRFactor", "1.3", "HDR brightness headroom", "HDR",
             "Experiment with HDR brightness headroom. This is not a general fix for dark scenes.",
             caution=EXPERIMENT + " Requires HDR output and a compatible display."),
    *(Command(variable, title, "Inspect settings", f'/dump GetCVar("{variable}")',
              "Inspect this rendering setting without changing it.", "Inspect only",
              "No tuning value is recommended: the live range and visual benefit have not been verified.",
              _wiki(variable), variable)
      for variable, title in (("giQuality", "Inspect global illumination"),
                              ("graphicsLightMode", "Inspect lighting mode"),
                              ("pbrLiquidDetail", "Inspect water detail"),
                              ("SkyCloudLOD", "Inspect cloud detail"),
                              ("SSAO", "Inspect ambient occlusion"))),
    _setting("autoLootDefault", "1", "Automatic looting", "Convenience",
             "Collect loot automatically when the loot window opens.", status="Reference",
             caution="This does not automatically open corpses or sell items.", source=_wiki("autoLootDefault")),
    Command("junk-confirmation", "Skip sell-junk confirmation", "Addons", "/aajs on",
            "Requires Junk & Repair Manager. Accept the confirmation after you click Sell Junk.",
            "Addon required", "Install the Forever version first. /aajs off restores the confirmation. "
            "This command does not enable automatic selling on vendor visits.", ADDON_SOURCE),
    Command("junk-automatic", "Automatically sell junk at vendors", "Addons", "/jrm",
            "Requires Junk & Repair Manager. Open its settings and enable Automatically sell junk at vendor.",
            "Addon required", "The command opens settings; enable automatic selling separately. "
            "Turn it off in the same panel to return to manual sales.", ADDON_SOURCE),
)
CATEGORIES = ("All categories", *dict.fromkeys(c.category for c in COMMANDS))


def find_commands(query="", category="All categories"):
    def folded(value):
        return unicodedata.normalize("NFKC", value).casefold()
    terms = folded(query).split()
    return [entry for entry in COMMANDS
            if (category == "All categories" or entry.category == category)
            and all(term in folded(" ".join((entry.title, entry.command, entry.description,
                                             entry.category, entry.status, entry.caution))) for term in terms)]


def describe(entry):
    parts = [entry.title, f"{entry.category} · {entry.status}", entry.description,
             "Command\n" + entry.command, entry.caution]
    if entry.inspect:
        parts.append("Read current value before changing\n" + entry.inspect)
    if entry.restore:
        parts.append("Restore game default\n" + entry.restore +
                     "\nDefault is not your previous custom value. Record that value to restore it exactly.")
    parts.append(f"Reference reviewed {REVIEWED}\n{entry.source}\n"
                 "The companion has not checked your installed client or run this command.")
    return "\n\n".join(parts)
