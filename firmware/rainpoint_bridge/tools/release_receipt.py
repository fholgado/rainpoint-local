"""Record the actual PlatformIO upload layout without flashing hardware."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

Import("env")  # type: ignore[name-defined]


def record_release(source, target, env):
    project = Path(env.subst("$PROJECT_DIR"))
    root = project.parents[1]
    build = Path(env.subst("$BUILD_DIR"))
    images = list(env.get("FLASH_EXTRA_IMAGES", [])) + [
        (env.subst("$ESP32_APP_OFFSET"), env.subst("$BUILD_DIR/${PROGNAME}.bin"))
    ]
    parts = []
    for offset, filename in images:
        path = Path(env.subst(str(filename)))
        destination = build / path.name
        if path.resolve() != destination.resolve():
            shutil.copyfile(path, destination)
        content = destination.read_bytes()
        parts.append({"path": path.name, "offset": int(str(offset), 0),
                      "size_bytes": len(content),
                      "sha256": hashlib.sha256(content).hexdigest()})
    receipt = {
        "schema_version": 1,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root)),
        "version": env["RAINPOINT_BUILD_VERSION"],
        "variant": "unified", "environment": env.subst("$PIOENV"),
        "board": env.subst("$BOARD"), "parts": sorted(parts, key=lambda p: p["offset"]),
    }
    (build / "release-input.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print("Recorded verified-build inputs (no USB or RF transmission)")


env.AddCustomTarget("release_receipt", "$BUILD_DIR/${PROGNAME}.bin", record_release,
                    title="Record alpha packaging inputs", always_build=True)
