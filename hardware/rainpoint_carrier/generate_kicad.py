#!/usr/bin/env python3
"""Generate the RainPoint carrier KiCad project from verified dimensions.

Run this with KiCad's bundled Python interpreter so the saved board is always
written by KiCad itself rather than by a hand-maintained S-expression writer.
"""

import json
import sys
import uuid
from pathlib import Path

import pcbnew


PROJECT_NAME = "rainpoint_carrier"
BOARD_LEFT = 100.0
BOARD_TOP = 50.0
BOARD_WIDTH = 68.0
BOARD_HEIGHT = 66.0
BOARD_BOTTOM = BOARD_TOP + BOARD_HEIGHT


def mm(value):
    return pcbnew.FromMM(value)


def point(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def physical_point(x, y):
    """Convert lower-left fit-check coordinates to KiCad page coordinates."""
    return point(BOARD_LEFT + x, BOARD_BOTTOM - y)


def new_uuid():
    return str(uuid.uuid4())


def add_net(board, name):
    net = pcbnew.NETINFO_ITEM(board, name)
    board.Add(net)
    return net


def configure_field(field, position, layer, visible=True, size=1.0):
    field.SetPosition(position)
    field.SetLayer(layer)
    field.SetTextSize(point(size, size))
    field.SetTextThickness(mm(0.15))
    field.SetVisible(visible)


def add_header(
    board, reference, value, positions, pad_nets, component_path, library_directory
):
    footprint = pcbnew.FootprintLoad(str(library_directory), value)
    if footprint is None:
        raise RuntimeError("unable to load footprint " + value)
    footprint.SetReference(reference)
    footprint.SetValue(value)
    footprint.SetFPIDAsString("RainPoint_Carrier:" + value)
    footprint.SetPath(pcbnew.KIID_PATH(component_path))
    footprint.SetPosition(positions[0])
    for pad in footprint.Pads():
        number = int(pad.GetNumber())
        pad.SetNet(pad_nets[number])
    board.Add(footprint)
    return footprint


def add_mounting_hole(board, reference, position):
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(reference)
    footprint.SetValue("MountingHole_3.2mm_M3")
    footprint.SetAttributes(pcbnew.FP_THROUGH_HOLE)
    footprint.SetAllowMissingCourtyard(True)
    footprint.SetBoardOnly(True)
    footprint.SetExcludedFromBOM(True)
    footprint.SetExcludedFromPosFiles(True)
    footprint.SetPosition(position)
    pad = pcbnew.PAD(footprint)
    pad.SetNumber("")
    pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(point(3.2, 3.2))
    pad.SetDrillSize(point(3.2, 3.2))
    pad.SetLayerSet(pad.UnplatedHoleMask())
    pad.SetPosition(position)
    footprint.Add(pad)
    configure_field(footprint.Reference(), position, pcbnew.F_Fab, visible=False)
    configure_field(footprint.Value(), position, pcbnew.F_Fab, visible=False)
    board.Add(footprint)


def add_capacitor(
    board, reference, center, power_net, ground_net, component_path, library_directory
):
    footprint = pcbnew.FootprintLoad(str(library_directory), "C_0805_2012Metric")
    if footprint is None:
        raise RuntimeError("unable to load capacitor footprint")
    footprint.SetReference(reference)
    footprint.SetValue("100nF" if reference == "C1" else "10uF")
    footprint.SetFPIDAsString("RainPoint_Carrier:C_0805_2012Metric")
    footprint.SetPath(pcbnew.KIID_PATH(component_path))
    footprint.SetPosition(center)
    footprint.FindPadByNumber("1").SetNet(power_net)
    footprint.FindPadByNumber("2").SetNet(ground_net)
    board.Add(footprint)


def add_track(board, net, layer, width, coordinates):
    for start, end in zip(coordinates, coordinates[1:]):
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(point(*start))
        track.SetEnd(point(*end))
        track.SetWidth(mm(width))
        track.SetLayer(layer)
        track.SetNet(net)
        track.SetHasSolderMask(False)
        board.Add(track)


def add_via(board, net, position):
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(point(*position))
    via.SetWidth(mm(0.70))
    via.SetDrill(mm(0.30))
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNet(net)
    board.Add(via)


def add_shape(board, shape_type, layer, start, end, width=0.2, radius=None):
    shape = pcbnew.PCB_SHAPE(board)
    shape.SetShape(shape_type)
    shape.SetStart(point(*start))
    shape.SetEnd(point(*end))
    if radius is not None:
        shape.SetCornerRadius(mm(radius))
    shape.SetLayer(layer)
    shape.SetWidth(mm(width))
    board.Add(shape)
    return shape


def add_text(board, text, position, layer, size=1.0, thickness=0.15, mirrored=False):
    item = pcbnew.PCB_TEXT(board)
    item.SetText(text)
    item.SetPosition(point(*position))
    item.SetLayer(layer)
    item.SetTextSize(point(size, size))
    item.SetTextThickness(mm(thickness))
    item.SetMirrored(mirrored)
    board.Add(item)


def add_polygon(zone, coordinates):
    outline = zone.Outline()
    index = outline.NewOutline()
    for x, y in coordinates:
        outline.Append(mm(x), mm(y), index)


def add_ground_zone(board, ground_net, layer):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(ground_net)
    zone.SetLocalClearance(mm(0.3))
    zone.SetMinThickness(mm(0.25))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    add_polygon(
        zone,
        (
            (100.5, 50.5),
            (167.5, 50.5),
            (167.5, 115.5),
            (100.5, 115.5),
        ),
    )
    board.Add(zone)


def add_keepout(board, layer):
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetIsRuleArea(True)
    zone.SetDoNotAllowTracks(True)
    zone.SetDoNotAllowVias(True)
    zone.SetDoNotAllowPads(True)
    zone.SetDoNotAllowZoneFills(True)
    zone.SetDoNotAllowFootprints(False)
    add_polygon(zone, ((107, 50.5), (138, 50.5), (138, 68.5), (107, 68.5)))
    board.Add(zone)


def create_board(output, identifiers):
    board = pcbnew.BOARD()
    board.SetFileName(str(output))
    settings = board.GetDesignSettings()
    settings.SetBoardThickness(mm(1.6))
    settings.SetCopperLayerCount(2)
    settings.m_MinClearance = mm(0.20)
    settings.m_TrackMinWidth = mm(0.25)
    settings.m_MinThroughDrill = mm(0.30)
    settings.m_HoleClearance = mm(0.25)
    settings.m_HoleToHoleMin = mm(0.25)
    settings.m_ViasMinSize = mm(0.60)
    settings.m_MicroViasMinDrill = mm(0.30)

    title = board.GetTitleBlock()
    title.SetTitle("RainPoint radio-node carrier")
    title.SetRevision("A")
    title.SetCompany("RainPoint Local project")
    title.SetComment(0, "Physically verified 30-pin ESP32 footprint")

    nets = {
        name: add_net(board, "/" + name)
        for name in (
            "GND",
            "3V3",
            "RADIO_GDO0",
            "RADIO_CSN",
            "RADIO_SCK",
            "RADIO_MOSI",
            "RADIO_MISO",
            "RADIO_GDO2",
        )
    }
    library_directory = output.parent / "RainPoint_Carrier.pretty"

    left_functions = (
        "VIN",
        "GND",
        "GPIO13",
        "GPIO12",
        "GPIO14",
        "GPIO27",
        "GPIO26",
        "GPIO25",
        "GPIO33",
        "GPIO32",
        "GPIO35",
        "GPIO34",
        "VN",
        "VP",
        "EN",
    )
    right_functions = (
        "3V3",
        "GND",
        "GPIO15",
        "GPIO2",
        "GPIO4",
        "RX2",
        "TX2",
        "GPIO5",
        "GPIO18",
        "GPIO19",
        "GPIO21",
        "RX0",
        "TX0",
        "GPIO22",
        "GPIO23",
    )
    j1_positions = [physical_point(9.68, 10.01 + index * 2.54) for index in range(15)]
    j2_positions = [physical_point(35.08, 10.01 + index * 2.54) for index in range(15)]
    j1_used = {
        2: nets["GND"],
        6: nets["RADIO_CSN"],
        7: nets["RADIO_GDO0"],
        8: nets["RADIO_GDO2"],
    }
    j2_used = {
        1: nets["3V3"],
        9: nets["RADIO_SCK"],
        10: nets["RADIO_MISO"],
        15: nets["RADIO_MOSI"],
    }
    for number, function in enumerate(left_functions, 1):
        if number not in j1_used:
            j1_used[number] = add_net(
                board, "unconnected-(J1-%s-Pad%d)" % (function, number)
            )
    for number, function in enumerate(right_functions, 1):
        if number not in j2_used:
            j2_used[number] = add_net(
                board, "unconnected-(J2-%s-Pad%d)" % (function, number)
            )
    add_header(
        board,
        "J1",
        "ESP32_Left_1x15",
        j1_positions,
        j1_used,
        "/%s/%s" % (identifiers["root"], identifiers["J1"]),
        library_directory,
    )
    add_header(
        board,
        "J2",
        "ESP32_Right_1x15",
        j2_positions,
        j2_used,
        "/%s/%s" % (identifiers["root"], identifiers["J2"]),
        library_directory,
    )

    radio_positions = []
    for row in range(4):
        radio_positions.extend(
            (
                physical_point(41.00, 29.19 + row * 2.54),
                physical_point(43.54, 29.19 + row * 2.54),
            )
        )
    add_header(
        board,
        "J3",
        "CC1101_2x4",
        radio_positions,
        {
            1: nets["GND"],
            2: nets["3V3"],
            3: nets["RADIO_GDO0"],
            4: nets["RADIO_CSN"],
            5: nets["RADIO_SCK"],
            6: nets["RADIO_MOSI"],
            7: nets["RADIO_MISO"],
            8: nets["RADIO_GDO2"],
        },
        "/%s/%s" % (identifiers["root"], identifiers["J3"]),
        library_directory,
    )

    add_capacitor(
        board,
        "C1",
        point(146.5, 86.0),
        nets["3V3"],
        nets["GND"],
        "/%s/%s" % (identifiers["root"], identifiers["C1"]),
        library_directory,
    )
    add_capacitor(
        board,
        "C2",
        point(146.5, 89.0),
        nets["3V3"],
        nets["GND"],
        "/%s/%s" % (identifiers["root"], identifiers["C2"]),
        library_directory,
    )

    for reference, physical in zip(
        ("H1", "H2", "H3", "H4"),
        ((3.5, 3.5), (64.5, 3.5), (3.5, 62.5), (64.5, 62.5)),
    ):
        add_mounting_hole(board, reference, physical_point(*physical))

    # Rounded board outline and assembly outlines.
    add_shape(
        board,
        pcbnew.S_RECT,
        pcbnew.Edge_Cuts,
        (BOARD_LEFT, BOARD_TOP),
        (BOARD_LEFT + BOARD_WIDTH, BOARD_TOP + BOARD_HEIGHT),
        width=0.05,
        radius=0.8,
    )
    add_shape(board, pcbnew.S_RECT, pcbnew.F_SilkS, (108, 57.26), (137, 109), width=0.2)
    add_shape(board, pcbnew.S_RECT, pcbnew.F_SilkS, (139, 75.5), (167, 90.5), width=0.2)
    add_shape(board, pcbnew.S_RECT, pcbnew.Dwgs_User, (107, 50.5), (138, 68.5), width=0.2)

    add_text(board, "RAINPOINT RADIO NODE - REV A", (134, 113.0), pcbnew.F_SilkS, 1.1)
    add_text(board, "USB / POWER", (122.5, 110.5), pcbnew.F_SilkS, 0.9)
    add_text(board, "WI-FI ANTENNA - NO COPPER", (122.5, 52.5), pcbnew.F_SilkS, 0.8)
    add_text(board, "433 MHz ANTENNA ->", (154.0, 73.8), pcbnew.F_SilkS, 0.8)
    add_text(board, "ESP32 30-PIN", (122.5, 75.0), pcbnew.F_SilkS, 1.0)
    add_text(board, "CC1101", (154.0, 83.0), pcbnew.F_SilkS, 1.0)
    add_text(board, "3V3 ONLY", (146.0, 92.0), pcbnew.F_SilkS, 0.8)
    add_text(board, "github.com/fholgado/rainpoint-local", (134, 113.0), pcbnew.B_SilkS, 0.8, mirrored=True)
    add_text(board, "NODE: __________", (134, 110.5), pcbnew.B_SilkS, 0.8, mirrored=True)

    # The ESP32's right through-hole row is a barrier on both copper layers.
    # Route all left-row signals around the USB end, below the final header pad.
    add_track(
        board,
        nets["RADIO_GDO2"],
        pcbnew.B_Cu,
        0.30,
        (
            (109.68, 88.21),
            (106.0, 88.21),
            (106.0, 114.5),
            (155.0, 114.5),
            (155.0, 79.19),
            (143.54, 79.19),
        ),
    )
    add_track(
        board,
        nets["RADIO_CSN"],
        pcbnew.B_Cu,
        0.30,
        (
            (107.0, 93.29),
            (107.0, 113.5),
            (152.0, 113.5),
            (152.0, 84.27),
            (143.54, 84.27),
        ),
    )
    add_via(board, nets["RADIO_CSN"], (107.0, 93.29))
    add_track(
        board,
        nets["RADIO_CSN"],
        pcbnew.F_Cu,
        0.30,
        ((109.68, 93.29), (107.0, 93.29)),
    )
    add_track(
        board,
        nets["RADIO_GDO0"],
        pcbnew.B_Cu,
        0.30,
        (
            (109.68, 90.75),
            (108.0, 90.75),
            (108.0, 112.5),
            (138.5, 112.5),
            (138.5, 95.0),
        ),
    )
    add_via(board, nets["RADIO_GDO0"], (138.5, 95.0))
    add_track(
        board,
        nets["RADIO_GDO0"],
        pcbnew.F_Cu,
        0.30,
        ((138.5, 95.0), (138.5, 84.27), (141.0, 84.27)),
    )

    # Right-side SPI signals on F.Cu.
    add_track(board, nets["RADIO_SCK"], pcbnew.B_Cu, 0.30, ((135.08, 85.67), (137.0, 85.67), (141.00, 81.73)))
    add_track(board, nets["RADIO_MISO"], pcbnew.F_Cu, 0.30, ((135.08, 83.13), (137.0, 83.13), (140.94, 79.19), (141.00, 79.19)))
    add_track(board, nets["RADIO_MOSI"], pcbnew.F_Cu, 0.30, ((135.08, 70.43), (139.0, 70.43), (147.0, 78.43), (147.0, 80.27), (145.54, 81.73), (143.54, 81.73)))

    # Power and ground trunks.
    add_track(
        board,
        nets["3V3"],
        pcbnew.F_Cu,
        0.50,
        ((135.08, 105.99), (140.0, 105.99), (140.0, 92.0), (146.0, 86.81), (143.54, 86.81)),
    )
    add_track(board, nets["3V3"], pcbnew.B_Cu, 0.50, ((143.54, 86.81), (145.5, 86.0)))
    add_track(board, nets["3V3"], pcbnew.B_Cu, 0.50, ((145.5, 86.0), (145.5, 89.0)))

    add_keepout(board, pcbnew.F_Cu)
    add_keepout(board, pcbnew.B_Cu)
    add_ground_zone(board, nets["GND"], pcbnew.F_Cu)
    add_ground_zone(board, nets["GND"], pcbnew.B_Cu)

    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(output), board)


def effects(hidden=False, justify=None):
    parts = ["(effects (font (size 1.27 1.27))"]
    if justify:
        parts.append(" (justify %s)" % justify)
    if hidden:
        parts.append(" (hide yes)")
    parts.append(")")
    return "".join(parts)


def symbol_properties(reference, value, description):
    return "\n".join(
        (
            '(property "Reference" "%s" (at 0 22.86 0) %s)' % (reference, effects()),
            '(property "Value" "%s" (at 0 20.32 0) %s)' % (value, effects()),
            '(property "Footprint" "RainPoint_Carrier:%s" (at 0 0 0) %s)' % (value, effects(True)),
            '(property "Datasheet" "" (at 0 0 0) %s)' % effects(True),
            '(property "Description" "%s" (at 0 0 0) %s)' % (description, effects(True)),
        )
    )


def connector_library_symbol(lib_id, pin_names):
    symbol_name = lib_id.split(":", 1)[-1]
    pins = []
    pin_count = len(pin_names)
    first_y = -((pin_count - 1) * 2.54) / 2
    for index, name in enumerate(pin_names, 1):
        y = first_y + (index - 1) * 2.54
        pins.append(
            '(pin passive line (at 10.16 %.3f 180) (length 5.08) '
            '(name "%s" %s) (number "%d" %s))'
            % (y, name, effects(), index, effects())
        )
    return """
(symbol "%s"
  (pin_names (offset 1.016))
  (exclude_from_sim no) (in_bom yes) (on_board yes)
  %s
  (symbol "%s_1_1"
    (rectangle (start -5.08 -20.32) (end 5.08 20.32)
      (stroke (width 0.254) (type default)) (fill (type background)))
    %s)
  (embedded_fonts no))
""" % (
        lib_id,
        symbol_properties("J", symbol_name, "RainPoint carrier socket"),
        symbol_name,
        "\n".join(pins),
    )


def capacitor_library_symbol():
    return """
(symbol "RainPoint:Capacitor"
  (pin_names (offset 0) (hide yes))
  (exclude_from_sim no) (in_bom yes) (on_board yes)
  %s
  (symbol "Capacitor_1_1"
    (polyline (pts (xy -0.762 2.032) (xy -0.762 -2.032))
      (stroke (width 0.508) (type default)) (fill (type none)))
    (polyline (pts (xy 0.762 2.032) (xy 0.762 -2.032))
      (stroke (width 0.508) (type default)) (fill (type none)))
    (pin passive line (at -5.08 0 0) (length 4.318)
      (name "1" %s) (number "1" %s))
    (pin passive line (at 5.08 0 180) (length 4.318)
      (name "2" %s) (number "2" %s)))
  (embedded_fonts no))
""" % (
        symbol_properties("C", "Capacitor", "Local CC1101 supply decoupling"),
        effects(),
        effects(),
        effects(),
        effects(),
    )


def instance_symbol(lib_id, reference, value, position, pin_count, footprint, symbol_uuid):
    if pin_count == 2:
        reference_position = (position[0], position[1] - 3.0)
        value_position = (position[0], position[1] + 3.0)
    else:
        reference_position = (position[0], position[1] - 22.86)
        value_position = (position[0], position[1] - 20.32)
    pin_entries = "\n".join(
        '(pin "%d" (uuid "%s"))' % (number, new_uuid())
        for number in range(1, pin_count + 1)
    )
    return """
(symbol
  (lib_id "%s") (at %.3f %.3f 0) (unit 1)
  (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
  (uuid "%s")
  (property "Reference" "%s" (at %.3f %.3f 0) %s)
  (property "Value" "%s" (at %.3f %.3f 0) %s)
  (property "Footprint" "RainPoint_Carrier:%s" (at %.3f %.3f 0) %s)
  (property "Datasheet" "" (at %.3f %.3f 0) %s)
  (property "Description" "RainPoint carrier component" (at %.3f %.3f 0) %s)
  %s
  (instances (project "%s"
    (path "/ROOT_UUID" (reference "%s") (unit 1)))))
""" % (
        lib_id,
        position[0],
        position[1],
        symbol_uuid,
        reference,
        reference_position[0],
        reference_position[1],
        effects(),
        value,
        value_position[0],
        value_position[1],
        effects(),
        footprint,
        position[0],
        position[1],
        effects(True),
        position[0],
        position[1],
        effects(True),
        position[0],
        position[1],
        effects(True),
        pin_entries,
        PROJECT_NAME,
        reference,
    )


def label(name, position):
    return '(label "%s" (at %.3f %.3f 0) %s (uuid "%s"))' % (
        name,
        position[0],
        position[1],
        effects(justify="left bottom"),
        new_uuid(),
    )


def no_connect(position):
    return '(no_connect (at %.3f %.3f) (uuid "%s"))' % (
        position[0],
        position[1],
        new_uuid(),
    )


def connector_pin_position(origin, pin_count, pin_number):
    first_y = -((pin_count - 1) * 2.54) / 2
    # The symbol-instance coordinate transform reverses the local Y direction
    # used by the embedded library graphics.
    return (origin[0] + 10.16, origin[1] - first_y - (pin_number - 1) * 2.54)


def create_schematic(output, identifiers):
    root_uuid = identifiers["root"]
    left_names = (
        "VIN", "GND", "GPIO13", "GPIO12", "GPIO14", "GPIO27", "GPIO26", "GPIO25",
        "GPIO33", "GPIO32", "GPIO35", "GPIO34", "VN", "VP", "EN",
    )
    right_names = (
        "3V3", "GND", "GPIO15", "GPIO2", "GPIO4", "RX2", "TX2", "GPIO5",
        "GPIO18", "GPIO19", "GPIO21", "RX0", "TX0", "GPIO22", "GPIO23",
    )
    radio_names = ("GND", "VCC", "GDO0", "CSN", "SCK", "MOSI", "MISO/GDO1", "GDO2")
    origins = {"J1": (38.1, 76.2), "J2": (38.1, 127.0), "J3": (104.14, 101.6)}
    used = {
        "J1": {2: "GND", 6: "RADIO_CSN", 7: "RADIO_GDO0", 8: "RADIO_GDO2"},
        "J2": {1: "3V3", 9: "RADIO_SCK", 10: "RADIO_MISO", 15: "RADIO_MOSI"},
        "J3": {
            1: "GND", 2: "3V3", 3: "RADIO_GDO0", 4: "RADIO_CSN",
            5: "RADIO_SCK", 6: "RADIO_MOSI", 7: "RADIO_MISO", 8: "RADIO_GDO2",
        },
    }

    connectivity = []
    for reference, pin_count in (("J1", 15), ("J2", 15), ("J3", 8)):
        for pin_number in range(1, pin_count + 1):
            position = connector_pin_position(origins[reference], pin_count, pin_number)
            if pin_number in used[reference]:
                connectivity.append(label(used[reference][pin_number], position))
            else:
                connectivity.append(no_connect(position))

    capacitor_origins = {"C1": (101.6, 139.7), "C2": (101.6, 149.86)}
    for origin in capacitor_origins.values():
        connectivity.append(label("3V3", (origin[0] - 5.08, origin[1])))
        connectivity.append(label("GND", (origin[0] + 5.08, origin[1])))

    symbols = [
        instance_symbol("RainPoint:ESP32_Left_1x15", "J1", "ESP32_Left_1x15", origins["J1"], 15, "ESP32_Left_1x15", identifiers["J1"]),
        instance_symbol("RainPoint:ESP32_Right_1x15", "J2", "ESP32_Right_1x15", origins["J2"], 15, "ESP32_Right_1x15", identifiers["J2"]),
        instance_symbol("RainPoint:CC1101_2x4", "J3", "CC1101_2x4", origins["J3"], 8, "CC1101_2x4", identifiers["J3"]),
        instance_symbol("RainPoint:Capacitor", "C1", "100nF", capacitor_origins["C1"], 2, "C_0805_2012Metric", identifiers["C1"]),
        instance_symbol("RainPoint:Capacitor", "C2", "10uF", capacitor_origins["C2"], 2, "C_0805_2012Metric", identifiers["C2"]),
    ]

    content = """(kicad_sch
  (version 20250114)
  (generator "rainpoint_carrier_generator")
  (generator_version "1.0")
  (uuid "%s")
  (paper "A4")
  (title_block
    (title "RainPoint radio-node carrier")
    (date "2026-08-12")
    (rev "A")
    (company "RainPoint Local project")
    (comment 1 "Physically verified 30-pin ESP32 footprint"))
  (lib_symbols
    %s
    %s
    %s
    %s)
  %s
  %s
  (text "USB-C powered ESP32 carrier; CC1101 is 3V3 only"
    (exclude_from_sim no) (at 38.1 38.1 0)
    %s (uuid "%s"))
  (sheet_instances (path "/" (page "1")))
  (embedded_fonts no))
""" % (
        root_uuid,
        connector_library_symbol("RainPoint:ESP32_Left_1x15", left_names),
        connector_library_symbol("RainPoint:ESP32_Right_1x15", right_names),
        connector_library_symbol("RainPoint:CC1101_2x4", radio_names),
        capacitor_library_symbol(),
        "\n".join(connectivity),
        "\n".join(symbols).replace("ROOT_UUID", root_uuid),
        effects(),
        new_uuid(),
    )
    output.write_text(content, encoding="utf-8")


def create_project(output):
    project = {
        "board": {},
        "boards": [],
        "cvpcb": {},
        "erc": {},
        "libraries": {},
        "meta": {"filename": output.name, "version": 1},
        "net_settings": {"classes": [], "meta": {"version": 3}},
        "pcbnew": {},
        "schematic": {},
        "text_variables": {},
    }
    output.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")


def connector_footprint(name, rows, columns=1, row_spacing=2.54, column_spacing=2.54):
    pads = []
    number = 1
    for row in range(rows):
        for column in range(columns):
            shape = "rect" if number == 1 else "circle"
            pads.append(
                '(pad "%d" thru_hole %s (at %.3f %.3f) (size 2 2) '
                '(drill 1) (layers "*.Cu" "*.Mask"))'
                % (number, shape, column * column_spacing, -row * row_spacing)
            )
            number += 1
    width = max(2.54, (columns - 1) * column_spacing + 2.54)
    height = max(2.54, (rows - 1) * row_spacing + 2.54)
    return """(footprint "%s"
  (version 20250114) (generator "rainpoint_carrier_generator")
  (layer "F.Cu")
  (descr "RainPoint carrier component")
  (attr through_hole)
  (property "Reference" "REF**" (at %.3f -2 0) (layer "F.Fab")
    (hide yes) (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "%s" (at %.3f %.3f 0) (layer "F.Fab")
    (effects (font (size 1 1) (thickness 0.15))))
  (property "Description" "RainPoint carrier component" (at 0 0 0) (layer "F.Fab")
    (hide yes) (effects (font (size 1.27 1.27))))
  (fp_rect (start -1.27 -1.27) (end %.3f %.3f)
    (stroke (width 0.2) (type default)) (fill none) (layer "F.Fab"))
  %s
  (embedded_fonts no))
""" % (
        name,
        width / 2 - 1.27,
        name,
        width / 2 - 1.27,
        height + 1.5,
        width - 1.27,
        height - 1.27,
        "\n  ".join(pads),
    )


def capacitor_footprint():
    return """(footprint "C_0805_2012Metric"
  (version 20250114) (generator "rainpoint_carrier_generator")
  (layer "B.Cu")
  (descr "RainPoint carrier component")
  (attr smd)
  (property "Reference" "REF**" (at 0 1.8 0) (layer "B.SilkS")
    (effects (font (size 0.8 0.8) (thickness 0.15)) (justify mirror)))
  (property "Value" "C_0805_2012Metric" (at 0 -1.8 0) (layer "B.Fab")
    (effects (font (size 0.8 0.8) (thickness 0.15)) (justify mirror)))
  (property "Description" "RainPoint carrier component" (at 0 0 0) (layer "B.Fab")
    (hide yes) (effects (font (size 1.27 1.27)) (justify mirror)))
  (fp_rect (start -2 -1) (end 2 1)
    (stroke (width 0.15) (type default)) (fill none) (layer "B.CrtYd"))
  (pad "1" smd roundrect (at -1 0) (size 1.2 1.4)
    (layers "B.Cu" "B.Paste" "B.Mask") (roundrect_rratio 0.2))
  (pad "2" smd roundrect (at 1 0) (size 1.2 1.4)
    (layers "B.Cu" "B.Paste" "B.Mask") (roundrect_rratio 0.2))
  (embedded_fonts no))
"""


def create_libraries(output_directory):
    symbol_library = """(kicad_symbol_lib
  (version 20250114)
  (generator "rainpoint_carrier_generator")
  %s
  %s
  %s
  %s)
""" % (
        connector_library_symbol(
            "ESP32_Left_1x15",
            (
                "VIN", "GND", "GPIO13", "GPIO12", "GPIO14", "GPIO27", "GPIO26", "GPIO25",
                "GPIO33", "GPIO32", "GPIO35", "GPIO34", "VN", "VP", "EN",
            ),
        ),
        connector_library_symbol(
            "ESP32_Right_1x15",
            (
                "3V3", "GND", "GPIO15", "GPIO2", "GPIO4", "RX2", "TX2", "GPIO5",
                "GPIO18", "GPIO19", "GPIO21", "RX0", "TX0", "GPIO22", "GPIO23",
            ),
        ),
        connector_library_symbol(
            "CC1101_2x4",
            ("GND", "VCC", "GDO0", "CSN", "SCK", "MOSI", "MISO/GDO1", "GDO2"),
        ),
        capacitor_library_symbol().replace('"RainPoint:Capacitor"', '"Capacitor"'),
    )
    # Library symbols use names without a library prefix; embedded schematic
    # copies retain the prefix in their lib_id.
    symbol_library = symbol_library.replace('symbol "RainPoint:', 'symbol "')
    (output_directory / "RainPoint.kicad_sym").write_text(symbol_library, encoding="utf-8")
    (output_directory / "sym-lib-table").write_text(
        '(sym_lib_table\n  (lib (name "RainPoint")(type "KiCad")'
        '(uri "${KIPRJMOD}/RainPoint.kicad_sym")(options "")(descr ""))\n)\n',
        encoding="utf-8",
    )

    footprint_directory = output_directory / "RainPoint_Carrier.pretty"
    footprint_directory.mkdir(exist_ok=True)
    (footprint_directory / "ESP32_Left_1x15.kicad_mod").write_text(
        connector_footprint("ESP32_Left_1x15", 15), encoding="utf-8"
    )
    (footprint_directory / "ESP32_Right_1x15.kicad_mod").write_text(
        connector_footprint("ESP32_Right_1x15", 15), encoding="utf-8"
    )
    (footprint_directory / "CC1101_2x4.kicad_mod").write_text(
        connector_footprint("CC1101_2x4", 4, columns=2), encoding="utf-8"
    )
    (footprint_directory / "C_0805_2012Metric.kicad_mod").write_text(
        capacitor_footprint(), encoding="utf-8"
    )
    (output_directory / "fp-lib-table").write_text(
        '(fp_lib_table\n  (lib (name "RainPoint_Carrier")(type "KiCad")'
        '(uri "${KIPRJMOD}/RainPoint_Carrier.pretty")(options "")(descr ""))\n)\n',
        encoding="utf-8",
    )


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_kicad.py OUTPUT_DIRECTORY")
    output_directory = Path(sys.argv[1]).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    identifiers = {
        "root": new_uuid(),
        "J1": new_uuid(),
        "J2": new_uuid(),
        "J3": new_uuid(),
        "C1": new_uuid(),
        "C2": new_uuid(),
    }
    create_libraries(output_directory)
    create_board(output_directory / (PROJECT_NAME + ".kicad_pcb"), identifiers)
    create_schematic(output_directory / (PROJECT_NAME + ".kicad_sch"), identifiers)
    create_project(output_directory / (PROJECT_NAME + ".kicad_pro"))


if __name__ == "__main__":
    main()
