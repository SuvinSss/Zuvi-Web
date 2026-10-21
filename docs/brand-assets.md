# Brand assets

Official logos came from the supplied "Zuuvi Light and Dark Logo Showcase" image and were cropped to each lockup and are otherwise unmodified: `frontend/src/assets/brand/zuvi-logo-{light,dark}.png`, marks `zuvi-mark-{light,dark}.png`, favicon `frontend/public/favicon.png`. The untouched reference is `frontend/src/assets/brand/source/`.

- Light surfaces use the light logo; the dark login panel uses the dark logo (`<Logo variant>`). Do not recolor, stretch or redraw.
- The source raster is ~722×240 px; it is crisp at ≤ 240 px wide on 1× and slightly soft on retina at larger sizes. **Request an SVG** from the brand owner to replace the PNGs.
- Design tokens (eco-green palette, radii, shadows) live in `frontend/src/styles/index.css` under `@theme`.
