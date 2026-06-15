from PIL import Image, ImageDraw

from src.ocr import crop_feature_control_symbol


def test_crop_feature_control_symbol_accepts_missing_top_frame():
    image = Image.new("RGB", (171, 43), "white")
    draw = ImageDraw.Draw(image)
    draw.line((11, 0, 11, 42), fill="black", width=1)
    draw.line((83, 0, 83, 42), fill="black", width=1)
    draw.line((164, 0, 164, 42), fill="black", width=1)
    draw.line((11, 42, 164, 42), fill="black", width=1)
    draw.polygon(((30, 28), (42, 10), (70, 10), (59, 28)), outline="black")

    symbol = crop_feature_control_symbol(image)

    assert symbol is not None
    assert symbol.size == (128, 128)
