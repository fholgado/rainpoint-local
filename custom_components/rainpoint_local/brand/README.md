# Integration icon

Original water/radio mark for this independent project, under the repository's
MIT license. It is not a RainPoint manufacturer or Home Assistant logo and does
not imply affiliation. Transparent PNGs are 256² and 512² pixels.

Rebuild on macOS from the repository root:

```sh
swift tools/generate_brand_icon.swift custom_components/rainpoint_local/brand
```

The code-native vector paths are the editable source. CI checks the PNG
dimensions and signature; actual HA rendering belongs to fresh-install testing.
