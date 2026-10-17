---
title: The traditional day
mode: learn
---

# The traditional day

A day in the panchangam runs sunrise to sunrise, not midnight to midnight. Five limbs read at
that sunrise give the day its name. The components below come from `leela_bricks`. They draw a
day; they do not compute one. This document fetches the day and binds it to them.

```canvas code id=td1
import json, urllib.request
_ports = json.load(urllib.request.urlopen('http://127.0.0.1:5010/bricks/data/panchanga.day'))
day = _ports['day']
day['tithi']['name'], day['nakshatra']['name'], day['masa']
```

`/bricks/data/panchanga.day` is Leela serving the brick's own ports, sample values included when
nothing better is at hand. Swap this cell for an almanac of your own and the three components
below follow it: they read `day`, and they do not care who filled it. The wiring stays in the
document, in the open.

```canvas brick id=td2 src=leela_bricks:panchanga.day emit_limb=limb
bind day = day
prop height = 250
```

```canvas code id=td3
limb = 'tithi'
```

```canvas data id=td4
bind text = f"You are looking at the **{limb}**: {day[limb]['name']}, until {day[limb].get('end','—')[11:16]}."
```

Click a limb above. The card hands the name back into this document, and the sentence follows it.

## The twenty-four horas

The panchangam cuts each daylight and each night into twelve horas, and the lords run in the
Chaldean order. The lord of the weekday takes the first hora of the day. Almost every language
that names a weekday for a planet follows that rule.

```canvas brick id=td5 src=leela_bricks:panchanga.horas emit_hora=hora
bind horas = day['horas']
prop height = 150
```

```canvas code id=td6
hora = day['horas'][0]
```

```canvas data id=td7
bind text = f"**{hora['name']}** hora, {hora['start'][11:16]} to {hora['end'][11:16]}, {hora['phase']}."
```

## Where the grahas actually are

```canvas brick id=td8 src=leela_bricks:panchanga.wheel emit_rasi=rasi
bind planets = day['planets']
bind highlight = day['moon_rasi']
prop height = 380
```

```canvas ask id=td9
explain nakshatra
```
