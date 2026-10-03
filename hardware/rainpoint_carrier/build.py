#!/usr/bin/env python3
"""Rebuild Rev B using KiCad, fail closed before producing order ZIPs.

KICAD_PYTHON must import pcbnew; KICAD_CLI must be KiCad 10. PDF generation
uses this script's Python, which must have reportlab. No live hardware access.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = "rainpoint_carrier"


def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True)


def main():
    cli = os.environ.get("KICAD_CLI", "kicad-cli")
    python = os.environ["KICAD_PYTHON"]
    version = subprocess.check_output([cli, "version"], text=True).strip()
    if not version.startswith("10."):
        raise SystemExit("Use KiCad 10; requalify other CAD versions explicitly")
    cad, fab, assembly = HERE / "kicad", HERE / "fabrication", HERE / "assembly"
    board, sch = cad / (NAME + ".kicad_pcb"), cad / (NAME + ".kicad_sch")
    run(python, HERE / "generate_kicad.py", cad)
    for path in (sch, cad / "RainPoint.kicad_sym"):
        path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n")
    run(cli, "sch", "erc", "--exit-code-violations", "-o", cad / (NAME + "-erc.txt"), sch)
    run(cli, "pcb", "drc", "--schematic-parity", "--exit-code-violations",
        "-o", cad / (NAME + "-drc.txt"), board)
    run(cli, "pcb", "export", "gerbers", "--layers",
        "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts", "-o", str(fab) + "/", board)
    run(cli, "pcb", "export", "drill", "--excellon-separate-th", "--generate-map",
        "--map-format", "svg", "--generate-report", "--report-path", fab / (NAME + "-drill-report.txt"),
        "-o", str(fab) + "/", board)
    run(cli, "pcb", "export", "ipcd356", "-o", fab / (NAME + ".d356"), board)
    run(cli, "pcb", "export", "stats", "-o", fab / (NAME + "-stats.txt"), board)
    run(cli, "pcb", "export", "gerbers", "--layers", "B.Paste", "-o", str(assembly) + "/", board)
    run(cli, "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "back",
        "--smd-only", "-o", assembly / "pcbway_cpl.csv", board)
    for side, layers, mirror in (("top", "F.Cu,F.Silkscreen,Edge.Cuts", []),
                                 ("bottom", "B.Cu,B.Silkscreen,Edge.Cuts", ["--mirror"])):
        run(cli, "pcb", "export", "svg", "--layers", layers, "--mode-single",
            "--fit-page-to-board", "--exclude-drawing-sheet", *mirror,
            "-o", HERE / "preview" / (NAME + "-" + side + ".svg"), board)
    run(cli, "sch", "export", "svg", "-o", str(cad / "schematic_preview") + "/", sch)
    # KiCad plots include trailing whitespace; normalize only SVG formatting.
    for folder in (fab, HERE / "preview", cad / "schematic_preview"):
        for svg in folder.glob("*.svg"):
            svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    # These tests inspect physical placement/nets in both CAD and its exported
    # fabrication netlist. A green DRC alone is deliberately insufficient.
    run(sys.executable, "-m", "unittest", "tests.test_carrier_pin_orientation", "-v")
    run(sys.executable, HERE / "generate_fit_check_pdf.py",
        ROOT / "output/pdf/rainpoint_carrier_rev_b_fit_check.pdf")
    output = ROOT / "output/manufacturing"
    output.mkdir(parents=True, exist_ok=True)
    suffixes = ("-F_Cu.gtl", "-B_Cu.gbl", "-F_Mask.gts", "-B_Mask.gbs",
                "-F_Silkscreen.gto", "-B_Silkscreen.gbo", "-Edge_Cuts.gm1",
                "-PTH.drl", "-NPTH.drl", "-job.gbrjob")
    files = [fab / (NAME + s) for s in suffixes]
    for path in files:
        if not path.is_file():
            raise RuntimeError("Missing fabrication output: " + str(path))
    for label, members in (("gerbers", files), ("pcba_gerbers", files + [assembly / (NAME + "-B_Paste.gbp")])):
        target = output / (NAME + "_rev_b_" + label + ".zip")
        with tempfile.NamedTemporaryFile(dir=output, suffix=".zip", delete=False) as tmp:
            temp = Path(tmp.name)
        try:
            with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                for source in members:
                    archive.write(source, source.name)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    for label in ("bom", "cpl"):
        shutil.copyfile(assembly / ("pcbway_" + label + ".csv"), output / (NAME + "_rev_b_pcba_" + label + ".csv"))
    outputs = sorted(output.glob(NAME + "_rev_b_*"))
    record = {"revision": "B", "kicad": version, "physical_acceptance": "pending",
              "source_board_sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
              "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs}}
    (fab / "rev_b_validation.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
