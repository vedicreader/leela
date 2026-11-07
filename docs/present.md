# Present a notebook

Leela shows the open notebook as slides. Leela has one presentation mode. You present from the IDE window. An audience window for a projector is optional. A presentation writes no file. Only a notebook can be presented.

In this guide, the presenter screen is the presentation in the IDE window. The audience window is a separate browser window that shows the slides to the room. The room is everyone who sees the audience window or a shared screen.

## Start

Select a cell. Then do one of these:

- Press Alt+R.
- Click Present at the right end of the tab row, in the header.
- Choose "Present from this cell" in the cell menu.

The View menu, the tab menu and the command palette also have Present. Each one starts the same presentation.

The presentation uses the text in the editor, with edits that you did not save. Leela does not export or save the notebook first.

The presentation starts at the slide that holds the selected cell. When the notebook metadata has `rise.start_slideshow_at: beginning`, Alt+R and Present start at the first slide. "Present from this cell" always starts at the selected cell.

The status line shows `Preparing slides…` while the server builds the slides. A notebook that is too large is refused. The message then says `Clear large outputs, then try again.`

| limit at start | value |
|---|---|
| cells | 2,000 |
| source of one cell | 1,000,000 characters |
| output text of one cell | 4,000,000 characters |
| slides | 9,999 |
| fragment groups on one slide | 49 |
| size of the request | 32 MB |

A slide with more than 49 fragment groups shows every extra fragment with the 49th group. The presenter sees a warning.

## The presenter screen

The slide fills the screen above a strip of controls. The strip hides after 3 seconds with no input. Move the pointer to the bottom edge, or move focus into the strip, to show it again.

The strip holds Previous, Next, the slide number, Run and Stop for each code cell of the slide, Audience window, the connection line, Notes, A-, the text size, A+, Full screen and End.

When a slide has more text than fits, Leela makes the text smaller down to a floor. At the floor, Leela cuts the slide at its margin. The presenter then sees `Slide N has more than fits. Split it or trim it.` At start, Leela names every slide that does not fit.

The Full screen button and the F key fill the screen with the presenter screen. When the browser refuses, the status line says `Use View › Enter Full Screen to fill the screen.`

## The audience window

The audience window is optional. Leela never opens it by itself.

1. Click Audience window in the strip.
2. Move the new window to the projector.
3. In that window, press F or double-click to fill the screen.
4. Go back to the IDE window and present from there.

The audience window has no controls. It takes only F and a double-click. Arrow keys in the audience window do nothing.

A second click on Audience window brings the open window to the front. It does not open another window. When the browser blocks the window, the strip says `The browser blocked the window. Click again.`

In the Mac app, Audience window opens the audience page in your system browser. Press F in that browser window to fill the screen.

The connection line says `Audience window: connected` while one or more audience windows are open. Otherwise it says `Audience window: not connected`. Closing the audience window does not end the presentation. When moves do not reach the server, the presenter sees `Moves are not reaching the audience window.`

## Keys

These keys work only during a presentation. They cannot be rebound. The keys help (the `present` section) lists them.

| key | action |
|---|---|
| Right arrow, Down arrow, Space, Page Down | next fragment group, then the next slide |
| Left arrow, Up arrow, Shift+Space, Page Up | back one fragment group; back onto a slide shows all its groups |
| N | Notes on or off |
| F | full screen on or off |
| X | laser on or off |
| B | blank screen on or off |
| Esc | close one thing |

A clicker that sends Page Down and Page Up works.

These rules apply to every key:

- A held key moves one step.
- A key with Cmd, Ctrl or Alt goes to the browser. The presentation does not use it.
- A key in a text field or in a demo does not move the slide.
- Space or Enter on a focused button presses the button. It does not move the slide.
- Leela's own shortcuts, such as Alt+R, Alt+W, `/` and the command palette, do nothing during a presentation.

Esc never ends the presentation. Esc closes the first open thing in this order:

1. the error panel
2. Notes
3. the laser
4. focus in a demo or a text field

With nothing open, Esc does nothing. An open dialog takes Esc for itself. In full screen, the browser takes Esc and leaves full screen. Esc within 400 ms after full screen ends does nothing.

## Notes

A `notes` cell holds speaker notes for the slide. Press N or click Notes to open the notes panel. The panel is closed when the presentation starts. It shows the notes, the title of the next slide and the time since the start.

Speaker notes are not on the audience page. They are visible to the room when you share the presenter screen. The panel says `The room can see these notes when you share this screen.` With one screen, open Notes only when the room cannot see it.

## Laser and blank

Press X to turn the laser on. The pointer position on the slide then shows as a dot on both screens. The dot fades after 1.5 seconds with no movement. Press X again or Esc to turn the laser off.

Press B to blank both screens. A blank screen shows the notebook name. Press B again to show the slide. The laser is off while the screen is blank.

## Text size

A- and A+ change the text size on both screens. Each press is a step of 10%. The size is between 50% and 250%. Leela keeps the size for each notebook.

`Text N px` beside A- and A+ is the body text size on the 1280x720 slide. It is not a promise of what the back row can read.

## Run and Stop

Each code cell on the slide has a Run button in the strip. Run runs the cell in the notebook's kernel. The output shows live on both screens.

Stop shows while the cell runs. Its place in the strip stays empty while the cell does not run. The other buttons do not move when a run starts or stops. Stop interrupts that cell. When the kernel ignores the interrupt, Stop restarts the kernel. Leela does not see a kernel that dies during a run. Press Stop to restart it.

Run in a presentation writes no file. Autosave pauses during a presentation. Leela schedules it again when the presentation ends. Files that your own code writes are not covered. A cell with side effects runs in front of the room.

When a run fails, the room sees the other outputs of that run, or no output. The room does not see the traceback. The presenter sees a panel with the error name, the message and the traceback. The panel says `The audience window does not show this error. The room can see it when you share this screen.` Click Show error to audience to send the error to the audience window. Esc or Close closes the panel. A new run of the cell closes it too. On one shared screen, the room can see the panel while it is open.

A kernel restart clears the output of every code cell on both screens. Run is then available again.

Run is off for a cell that changed or left the notebook after the presentation started. Its title says why.

The room screen shows text and images from outputs. Other output types show `This output type is not shown in presentations.` Output that is too long for one room message ends with `Output is too long for the room screen.`

## Demos

A rupaka demo on a slide runs on the presenter screen. The audience window shows a copy that follows the presenter's demo. The audience copy takes no input. It shows the choices of a gate, and the verdict after you settle the gate. It does not show Lock in or Try another. The answer of a gate goes to the room only after you settle the gate. A demo state that is too large is not sent. The presenter then sees `The demo is too large for the room screen.`

## What the room never sees

The server builds a separate copy of the slides for the room. That copy never holds these:

- notes cells and skipped cells, with their source, outputs, demos and images
- the title of the next slide
- a traceback, until you click Show error to audience
- the `answer` of a demo gate before you settle it, from a markdown fence, a `text/markdown` or `text/html` output, or an `application/vnd.rupaka+json` output
- the HTML page fallback of a rupaka output
- HTML comments, and `id`, `data-id` and `title` attributes
- links to files (only `http`, `https`, `mailto` and `#` links stay)
- a workspace path
- an image that is not a PNG, JPEG, GIF or WebP file, or that is not in a workspace folder

The server removes `<script>`, event attributes, `javascript:` links and remote images. The audience page also checks every block before it draws it. The audience page sends a Content-Security-Policy that allows scripts from Leela only. These are defenses. They are not a promise that nothing private can reach the room.

## What the room can still see

The room can see these:

- an answer written as plain text, in stream text, as escaped HTML or in code source
- a rupaka example shown inside another fence
- a gate whose answer is a state path or a derived value: the copy removes the `answer` key, and the state stays
- the gate's `why`, `prompt` and `options`
- image `alt` text
- stderr text
- everything on the presenter screen, when you share that screen

Do not tell the room that answers are hidden. Check a slide before you show it.

Output that a cell clears during its run (`clear_output`) can stay on both screens until the run ends. Leela applies the clear when kunda 0.0.10 or newer runs the kernel.

| image limit | value |
|---|---|
| one image | 8 MB |
| one side | 16,384 pixels |
| one image area | 40 million pixels |
| images in one presentation | 100 |
| all images | 64 MB |

## Slides from cells

Leela groups cells into slides with the RISE cell metadata `slideshow.slide_type`:

| `slide_type` | effect |
|---|---|
| `slide` | starts a new slide |
| `subslide` | starts a new slide; subslides are in the same line as slides |
| `fragment` | shows on the next step of the slide |
| `-` or none | continues the current slide |
| `skip` | not shown |
| `notes` | speaker notes for the slide |

The cell menu sets the slide type. With a cell selected and no text field in focus, Shift+I sets `slide`, Shift+B sets `subslide` and Shift+G sets `fragment`.

Leela ignores `rise.theme` and every other reveal.js option except `rise.start_slideshow_at`. Leela's own theme and fonts draw the slides on both screens. A theme change in the IDE during the presentation also changes the audience window.

When no cell is marked `slide` or `subslide`, a markdown cell with an H2 heading (`## `) starts a slide. Cells after it continue that slide. `fragment`, `notes`, `skip` and `-` marks do not stop this rule. A markdown cell with several H2 headings starts one slide. A `## ` line inside a code fence does not count. With no marks and no H2 headings, each cell is a slide.

A slide with only notes makes no slide. Its notes join the notes of the next slide.

## Reload and recovery

The server holds the presentation in memory. It holds the place, the blank screen, the text size, the theme, the latest output of each cell and the demo states.

- Reload the IDE tab: the presenter screen comes back at the same place. The audience window keeps working.
- Reload the audience window: it shows the current slide and outputs at once.
- A duplicated tab, or a tab that you go back to with the browser's Back or Forward, shows `Present from this tab?` with Take over. Take over moves the presenter screen to that tab. The old tab then says `The presentation moved to another tab.`
- A tab that lost its stored key shows `This tab lost its presenter key` with Start again.
- A presentation started from another page ends this one. This page says `Another presentation started.`
- When Leela restarts, the presentation is gone. The presenter sees `Leela restarted` with Start again. The audience window says `Leela restarted. The presenter can start again.`

Start again starts a new presentation from the live cells at the stored slide. It makes a new audience link. Open the audience window again after Start again.

## End

Click End. The button changes to `End now?`. Click it again within 3 seconds to end the presentation. Focus goes back to the selected cell in the notebook. The audience window shows an end card: `The presentation has ended.` and the notebook name.

## The audience link

The audience link holds a read-only key. A person with the link can see the slides and follow the presentation. That person cannot move the slides, run cells or end the presentation. The key stays in the address bar and in the browser history. In the Mac app, the system browser keeps the link in its history. The key stops working when the presentation ends.

## Not in this version

These are not built:

- Ask the room: polls and questions to the room, with hand counts and "What does this print?" questions
- saved talks as `<notebook>.talk.json`, a run log and a recap
- agent-drafted speaker notes
- a native audience window in the Mac app (the system browser opens the audience page)
- clicker blank keys other than B, such as `.`, and a clicker key that starts a presentation, such as F5
