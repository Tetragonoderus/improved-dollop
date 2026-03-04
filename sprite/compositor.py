"""
sprite/compositor.py

Composites an ordered list of PNG file paths into a single RGBA image
using Pillow. Each layer is pasted at (0, 0) in order, back to front.

Input:  list of Path objects from resolver.resolve()
Output: PIL.Image.Image (RGBA, 1280x850)
"""

from pathlib import Path
from PIL import Image

#for testsing
#from parser import parse
#from resolver import resolve

CANVAS_SIZE = (1280, 850)


def composite(layer_paths: list[Path]) -> Image.Image:
    """
    Paste each layer onto a transparent canvas in order.

    Parameters
    ----------
    layer_paths : list[Path]
        Ordered list of PNG paths, back to front. All should be 1280x850
        RGBA PNGs pre-positioned on their canvas.

    Returns
    -------
    PIL.Image.Image
        The final composited RGBA image.
    """
    canvas = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))

    for path in layer_paths:
        layer = Image.open(path).convert("RGBA")

        # All face/body layers are full-canvas so position is always (0,0).
        # If a layer is smaller than the canvas it likely needs to be placed
        # at a specific offset — handle that here once you know the offsets.
        canvas = Image.alpha_composite(canvas, layer)

    return canvas

if __name__ == "__main__":
   parse_data = parse('1eua')
   resolve_data = resolve(parse_data)
   test_image = composite(resolve_data)
   output_temp = Path("test_composite_image.png")
   test_image.save(output_temp)
   print(f"Success!")
