"""Non-destructive catalogue derivatives: originals remain in their existing field."""
from io import BytesIO
from PIL import Image, ImageOps, ImageDraw
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError


def display_image(source, *, remove_background=False):
    source.seek(0)
    try:
        with Image.open(source) as original:
            if original.width * original.height > 25_000_000:
                raise ValidationError('Product images must contain at most 25 megapixels.')
            image=ImageOps.exif_transpose(original).convert('RGBA')
            if remove_background:
                image.thumbnail((1200,1200),Image.Resampling.LANCZOS)
                pixels=image.load()
                corners=[(0,0),(image.width-1,0),(0,image.height-1),(image.width-1,image.height-1)]
                def white(pixel):
                    return min(pixel[:3]) >= 245 and max(pixel[:3])-min(pixel[:3]) <= 12
                if not all(white(pixels[x,y]) for x,y in corners):
                    raise ValidationError('Background removal supports plain white backgrounds only. Leave it off for this photo.')
                mask=Image.new('L',image.size)
                mask.putdata([255 if white(p) else 0 for p in image.getdata()])
                for corner in corners:
                    if mask.getpixel(corner)==255:
                        ImageDraw.floodfill(mask,corner,128)
                alpha=image.getchannel('A')
                alpha.putdata([0 if m==128 else a for m,a in zip(mask.getdata(),alpha.getdata())])
                image.putalpha(alpha)
                if not alpha.getbbox():
                    raise ValidationError('Background removal would erase this image. Upload with the option off.')
            # Trim transparent padding only. Never guess where food or packaging ends.
            bounds=image.getchannel('A').getbbox()
            if bounds:
                image=image.crop(bounds)
            image.thumbnail((1200,1200),Image.Resampling.LANCZOS)
            output=BytesIO()
            image.save(output,format='PNG',optimize=True)
            return ContentFile(output.getvalue(),name='display.png')
    finally:
        source.seek(0)
