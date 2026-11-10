# 看板娘 Live2D vendor tree

Same-origin static assets for the site-wide 看板娘 overlay.
Webpack copies this directory to `frontend/dist/live2d/` (URL prefix `/static/live2d/`).

Cubism 2 models (`.model.json` / `.moc`) and Cubism 3/4 models (`.model3.json` /
`.moc3`) are rendered by `l2d` (Cubism 2 & 6 official SDK wrapper) in the
mascot-widget chunk. The blog widget (`waifu-tips.js`) only supplies overlay
chrome (tips, tools); it does not draw. Vendor Cubism runtimes stay here for
license/redistribution and for the unused widget Cubism chunks.

## Layout

- `runtime/live2d.min.js` — Cubism 2 runtime
- `runtime/live2dcubismcore.min.js` — Cubism 3/4/5 Core
- `widget/waifu.css`, `widget/waifu-tips.js`, `widget/waifu-tips.json`
- `widget/chunk/index.js` — Cubism 2 loader
- `widget/chunk/index2.js` — Cubism 3/4 loader (Cubism Web SDK AppDelegate)
- `widget/autoload.js` — patched to `/static/live2d/` (no CDN at runtime)
- `models/<id>/` — demo packs (Cubism 2 and Cubism 3/4)
- `catalog.json` — build inventory; `entry` is relative to `/static/live2d/`
- `widget/waifu-tips.json` `models` — runtime catalog the widget actually loads

## Licenses

- Widget JS/CSS: GPL-3.0 (`widget/LICENSE`)
- Demo models: GPL-2.0 (`models/<id>/LICENSE`)
- Cubism 2 runtime and Cubism 5 Core: Live2D Inc. proprietary (`runtime/LICENSE.txt`)

Demo faces, not club-owned 看板娘 IP. Replacing models is a directory swap.
