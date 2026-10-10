# Companion artwork and font

`Marcellus-Regular.ttf` is the unmodified Marcellus typeface by Astigmatic, obtained
from the [Google Fonts repository](https://github.com/google/fonts/tree/main/ofl/marcellus).
Its SIL Open Font License and original copyright notice are in `Marcellus-OFL.txt`.
The Windows companion loads it privately for its own process; it does not install
a system font. Other platforms use Marcellus if available, otherwise Georgia.
This is a visual approximation of the requested fantasy interface typography.

`dark-leather.png` is an original material generated with the built-in image tool
on 2026-10-10. No screenshot or game asset was supplied to that generation. The
brass trim and button bevels are drawn by `wow_helper/theme.py`.

Generation prompt:

> Use case: stylized-concept. Asset type: a seamless tiling material texture for the narrow title bar of a desktop fantasy RPG companion. Generate one square 1024 by 1024 texture, filling the whole image edge to edge. Original hand-painted aged dark brown leather, nearly black espresso around #221a12, with restrained fine pores, subtle irregular scuffs, and very faint warm brown mottling. The texture must remain quiet and low contrast so small bright gold title text will be readable on top. Even flat illumination. Seamlessly tileable horizontally and vertically. No borders, frames, buttons, icons, text, symbols, stitching, holes, folds, objects, gradients, vignette, perspective, highlights, or copied game artwork. This is only the raw leather surface, an original material asset, not a UI mockup.

`red-leather.png` is a generated color variant of that original leather, used for
the buttons. The built-in image tool received only `dark-leather.png` and this
edit prompt:

> Use case: style-transfer. This image is an existing original leather material for a desktop app. Create a sibling texture variant for its buttons: preserve the fine leather grain and seamless edge-to-edge surface, but add a muted dark burgundy-red tint over the brown leather. Think worn oxblood leather with warm brown undertones, mainly #532820 with restrained raised-grain highlights around #784233. The brown material must still look tactile beneath the red shade. Even flat illumination, no gradient, no gloss, no hotspot, no vignette. No text, borders, buttons, UI mockups, objects, or new motifs. Keep it a square raw material texture filling the whole canvas.

The returned textures are 1254 × 1254. Tk downsamples them when loading the theme;
the bundled PNGs remain the original generated outputs. Hover, keyboard focus,
pressed, and disabled button states retain distinct edging and brightness.
