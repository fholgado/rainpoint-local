# Irrigation UI concept prompts — v1

Generated on 2026-09-28 with the built-in image-generation tool. These prompts
produce illustrative raster mockups, not screenshots of a working integration.
The overview image was the style reference for the other two screens.

## Overview

```text
Use case: ui-mockup
Asset type: High-fidelity proposed Home Assistant irrigation app screenshot, desktop landscape, approximately 1600 by 1050, crisp legible UI text. Flat screen capture, no laptop, no photo, no perspective, no decorative garden imagery.
Primary request: Design the daily overview for a hardware-independent Home Assistant irrigation app. This is concept 1 of a coordinated three-screen set; use an understated native-feeling Home Assistant shell, light theme, white surfaces on pale gray #F6F7F8, thin #E1E5E9 borders, charcoal text, cyan Home Assistant navigation selection, muted teal #147D73 irrigation controls, amber advisory warnings. Modern clean sans-serif, elegant spacing, 10–12px corner radii, restrained line icons. Professional, realistic application UI, not a marketing page.
Composition: left narrow Home Assistant sidebar about 185px wide with simple house logo and 'Home Assistant', navigation Overview, Energy, History, Irrigation (selected), Settings near bottom. Main area has top app bar 'Irrigation', navigation tabs 'Overview' active, 'Zones', 'Schedules', 'History', gear at right. Main content below uses generous but efficient spacing.
Header: 'Today’s irrigation', subtitle 'Tuesday, September 29', date previous/next controls and 'Today' control. Top-right primary 'Add schedule'. Small contextual line '16:50 · All valves idle'.
Three compact summary cards: '3' / 'Upcoming checks'; '30 min' / 'Watered today'; '1' / 'Schedule overlap'.
Amber slim advisory: 'Garden and Front Yard overlap for 10 minutes this evening.' right link 'Review schedules'. This is a warning, not a blocking error.
Main large white card about 75% content width titled 'Today’s schedule', with Agenda selected and Timeline unselected segmented control. Six readable chronological rows, all within screenshot. Columns Time, Zone, Duration, Status:
'06:00–06:20' | 'Garden' | '20 min · 2 valves' | teal outlined 'Completed'
'06:30–06:45' | 'Front Yard' | '15 min · 1 valve' | gray 'Skipped' with small secondary 'Soil already moist'
'06:50–07:00' | 'Patio' | '10 min · 1 valve' | teal outlined 'Completed'
A subtle 'Upcoming' divider:
'17:30–17:50' | 'Garden' | '20 min · 2 valves' | blue outlined 'Scheduled check' and small amber overlap icon
'17:40–17:55' | 'Front Yard' | '15 min · 1 valve' | blue outlined 'Scheduled check' and small amber overlap icon
'18:00–18:10' | 'Patio' | '10 min · 1 valve' | blue outlined 'Scheduled check'
Small note below list: 'Moisture and weather are checked again before each run.'
Right column narrow white 'Your zones' card, three rows each with compact restrained icon, label, supporting information and chevron:
Garden / '34% · 2 valves' / 'Next check 17:30'
Front Yard / '52% · 1 valve' / 'Next check 17:40'
Patio / 'Timer only · 1 valve' / 'Next check 18:00'
Bottom of right column a simple 'Forecast' card '20% rain chance' and '0.4 mm expected' with cloud line icon.
At bottom of page understated 'Includes schedules managed by Irrigation.' and tiny 'Design concept · Example data'.
Constraints: All scheduled occurrences are visible. Display planned versus actual outcomes truthfully. Upcoming states must say Scheduled check, not guaranteed watering. Past skip stays visible. Amber overlap advisory remains compatible with saving schedules. Do not invent extra counts, water-volume amounts, achievements, ads, charts, browser chrome, or huge empty space. Ensure text is accurate and alignment is excellent.
```

## Zone dashboard

```text
Use case: ui-mockup
Asset type: High-fidelity desktop application screenshot, same dimensions and visual quality as reference image.
Input image: style reference ONLY. Create a NEW screen of the SAME Irrigation application. Preserve Home Assistant sidebar, app bar, visual typography, native-feeling light theme, cyan selected navigation, white cards, pale gray background, muted teal controls, fine borders and radii. No perspective, no laptop, no decorative photo.
Primary request: Proposed Garden zone dashboard that is pleasant and practical for daily use. All values are illustrative, same sample data as overview.
Home Assistant sidebar Irrigation selected. Top app tabs Overview, Zones (selected), Schedules, History. Breadcrumb 'Zones / Garden'.
Main header 'Garden', subtitle '2 valves · 2 moisture sensors'. Near title small green 'Idle' badge. Top right teal primary 'Run now · 20 min', overflow menu. Directly below header slim row 'Automatic watering' toggle ON, 'Pause' link, 'Zone settings' link. Time context 'Tuesday, September 29 · 16:50'.
Three concise summary cards: first '34%' / 'Driest sensor' / 'Left bed · Updated 5 min ago'; second '17:30' / 'Next scheduled check' / '20 min · Every day'; third '20%' / 'Rain chance' / '0.4 mm expected'. Tiny green healthy indicators where appropriate, no invented water volume.
Main content two columns ~65%/35%.
LEFT upper white card 'Soil moisture', small 'Last 48 hours' selected menu. Two compact sensor readings with matching line dots 'Left bed 34%' and 'Right bed 42%', both 'Fresh'. Underneath a tasteful simple two-line moisture time-series, y-axis percentage 20,40,60,80, x-axis dates Sep27 Sep28 Sep29. Teal left-bed series ends at34%, blue right-bed series ends at42%. A dashed amber horizontal threshold at40%, clearly labelled 'Threshold 40%'. Lines should look plausible, no thick filled rainbow regions.
LEFT lower white card 'Today’s activity' with two rows: '06:00–06:20' / 'Watering completed' / 'Both valves reported closed'; '17:30–17:50' / 'Scheduled check' / 'Moisture and weather will be checked again'. Include 'View history' link.
RIGHT upper white card 'Watering decision', green/teal small badge 'Would water now', supporting 'Driest sensor is 34%, below 40%.' Rows 'Moisture threshold' '40%', 'Rain probability threshold' '70%', 'Meaningful rain' '3 mm'. Subtle note 'Preview only · Next check at17:30'. Link 'Edit watering rules'. Do not imply that the valve is currently watering.
RIGHT middle white card 'Schedules' with two rows 'Morning' / '06:00 ·20 min ·Every day', 'Evening' / '17:30 ·20 min ·Every day'. Show a small amber '10 min overlap' label on Evening; link 'View alongside other zones'. Add schedule secondary link.
Across bottom a white 'Valves' card with muted pill 'Sequential ·20 min total'. Two side-by-side valve rows 'Left bed' and 'Right bed', each Closed badge, '10 min', 'Device timer', 'Last report 2 min ago'. Do not pretend flow is measured. No Stop primary button while idle; Run now is the primary control.
Footer tiny 'Design concept · Example data'.
Constraints: This is a screenshot of a new proposed design, not a real installation. Maintain exact data coherence with reference: Garden2valves, moisture34%, next17:30, 20min total, rain20% and0.4mm. Keep UI text legible and avoid cramming. All main elements visible in one polished desktop screenshot.
```

## Schedule editor

```text
Use case: ui-mockup
Asset type: High-fidelity desktop application screenshot, same dimensions and visual quality as reference image.
Input image: style reference ONLY. Create a NEW screen for the same application, preserving the reference's Home Assistant sidebar, top app bar, typography, white/pale-gray light theme, blue navigation, teal buttons, fine borders, corner radii and spacing. Do not replicate the overview content. No laptop, no perspective, no marketing imagery.
Primary request: The proposed Irrigation schedule editor. Critical design goal: the user sees ALL other irrigations while editing. Overlap warnings are advisory and never disable Save.
Keep sidebar 'Irrigation' selected; top app navigation 'Schedules' selected, with Overview, Zones, Schedules, History. Main heading 'Edit schedule', breadcrumb 'Schedules / Front Yard', subtitle 'Evening watering'.
Two balanced columns: left form about 36%, right schedule context about 64%. Fit everything clearly without tiny text.
LEFT white form:
Title 'Schedule details'
Zone dropdown 'Front Yard'
Name input 'Evening watering'
Side-by-side time input '17:40' labelled 'Start time' and number '15 min' labelled 'Duration'.
'Repeat' with seven all-selected weekday circles M T W T F S S. Summary 'Every day · 17:40–17:55'.
Enabled toggle ON labelled 'Schedule enabled'.
Rule card: 'Use Front Yard watering rules', supporting 'Moisture and rain are checked before each run.'
A subtle duration summary '1 valve · 15 minutes'.
RIGHT large white preview card title 'Other irrigation on this day' with date 'Tue, Sep 29' and small previous/next arrows.
A horizontal detailed evening time chart with rows Garden, Front Yard (editing), Patio. Visible time window 17:00–18:30, labeled every 15 minutes: 17:00,17:15,17:30,17:45,18:00,18:15,18:30. Precisely aligned bars: Garden 17:30–17:50; Front Yard 17:40–17:55; Patio 18:00–18:10. Reference calculation: chart width represents 90 minutes, so Garden left 33.33% width22.22%; Front Yard left44.44% width16.67%; Patio left66.67% width11.11%. Front Yard bar has selection outline, Garden bar teal, Patio blue. Use short '20m', '15m', '10m' labels and exact start/end in row secondary text. Shade 17:40–17:50 amber across the two conflicting rows. A caption 'Evening detail · All times local'.
Directly under chart amber notice with title 'Overlaps Garden by 10 minutes', text '17:40–17:50 · Every day', and 'You can keep this time and save.' Link 'Edit Garden'.
Below the warning simple suggestion with clock icon 'Next clear slot: 18:10–18:25' and secondary action 'Use 18:10'. Important: 17:50 is NOT a clear 15-minute slot because Patio starts at18:00. No automatic schedule movement.
Below a compact readable 'Full day' list of ALL six planned occurrences, in two small columns or six compact rows: Garden06:00–06:20; Front Yard06:30–06:45; Patio06:50–07:00; Garden17:30–17:50; Front Yard17:40–17:55 (editing); Patio18:00–18:10. These must be readable and all present. Do not use a week calendar.
Page bottom action bar visible and spacious: left '1 overlap warning · Saving is allowed', right secondary 'Cancel', solid teal enabled primary 'Save schedule'.
Footer: 'Includes schedules managed by Irrigation.' and tiny 'Design concept · Example data'.
Constraints: Match the reference shell exactly as feasible. No greyed-out save, no blocking red alert, no confirmation modal, no automatic queue message for these independent valves. All numbers consistent. Highly polished legible screenshot.
```
