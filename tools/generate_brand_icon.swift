// Original RainPoint Local water/radio mark, licensed under the repository MIT license.
// Rebuild on macOS: swift tools/generate_brand_icon.swift custom_components/rainpoint_local/brand
// This is an independent project mark, not the manufacturer's or Home Assistant's logo.
import AppKit

guard CommandLine.arguments.count == 2 else {
    fatalError("Pass the existing integration brand directory")
}
let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
for size in [256, 512] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: size * 4, bitsPerPixel: 32)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let transform = AffineTransform(translationByX: 0, byY: CGFloat(size))
    (transform as NSAffineTransform).concat()
    let scale = NSAffineTransform()
    scale.scaleX(by: CGFloat(size) / 256, yBy: -CGFloat(size) / 256)
    scale.concat()
    NSColor(red: 0.04, green: 0.48, blue: 0.48, alpha: 1).setFill()
    let drop = NSBezierPath()
    drop.move(to: NSPoint(x: 128, y: 14))
    drop.curve(to: NSPoint(x: 218, y: 160), controlPoint1: NSPoint(x: 154, y: 56), controlPoint2: NSPoint(x: 218, y: 108))
    drop.curve(to: NSPoint(x: 128, y: 242), controlPoint1: NSPoint(x: 218, y: 210), controlPoint2: NSPoint(x: 177, y: 242))
    drop.curve(to: NSPoint(x: 38, y: 160), controlPoint1: NSPoint(x: 79, y: 242), controlPoint2: NSPoint(x: 38, y: 210))
    drop.curve(to: NSPoint(x: 128, y: 14), controlPoint1: NSPoint(x: 38, y: 108), controlPoint2: NSPoint(x: 102, y: 56))
    drop.close(); drop.fill()
    NSColor.white.setStroke(); NSColor.white.setFill()
    for (halfWidth, y) in [(48.0, 150.0), (27.0, 173.0)] {
        let arc = NSBezierPath()
        arc.lineWidth = 11; arc.lineCapStyle = .round
        arc.move(to: NSPoint(x: 128 - halfWidth, y: y))
        arc.curve(to: NSPoint(x: 128 + halfWidth, y: y),
            controlPoint1: NSPoint(x: 128 - halfWidth / 2, y: y - halfWidth / 2),
            controlPoint2: NSPoint(x: 128 + halfWidth / 2, y: y - halfWidth / 2))
        arc.stroke()
    }
    NSBezierPath(ovalIn: NSRect(x: 119, y: 190, width: 18, height: 18)).fill()
    NSGraphicsContext.restoreGraphicsState()
    let filename = size == 256 ? "icon.png" : "icon@2x.png"
    try bitmap.representation(using: .png, properties: [:])!.write(to: directory.appendingPathComponent(filename))
}
