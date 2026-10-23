# Doverfield Paper Mills: Calder mill operations and systems overview

Source: site visit on 11 September and two follow-up calls. Notes by Priya Nair.

Doverfield runs three mills in the Upper Midwest. The Calder mill is the target: three paper machines (PM1, PM2, PM3) producing containerboard, about 1,150 tons per day combined. PM3 is the newest and carries most of the margin.

## Plant systems
- Control: Rockwell ControlLogix PLCs on PM1 and PM2, a distributed control system on PM3 installed in 2019.
- Historian: a PI historian with about 38,000 tags at Calder.
- Maintenance: SAP PM. Roughly 11 planners and 60 maintenance technicians across three shifts.
- Condition monitoring today: route-based handheld vibration readings on 300 or so assets, monthly. No online monitoring except on the PM3 main drives, which come with the OEM's own closed system.
- OT network: segmented per the Purdue model, with no direct internet path from level 2 and below. Mill IT is one person plus a corporate security team.

## The problem in numbers
- 11 unplanned stops on PM3 in the last 12 months, 7 traced to dryer section bearings and gearbox faults.
- PM3 downtime costs about 38,000 dollars an hour in lost margin; the 11 events totaled 94 hours.
- Annual planned outage is the first week of April, 6 days, for all three machines. Sensor installation is only practical during outages or very short stops.
