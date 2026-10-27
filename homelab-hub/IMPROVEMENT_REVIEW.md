# Code and interface review — 27 October 2026

## Subsequent canvas refinement

The automation editor now shows compact connection handles on hover or while
connecting, following [draw.io's documented hover-and-drag interaction](https://www.drawio.com/docs/manual/editor/panels/connection-points-hide/).
The visible dots are small while their hit areas remain 28 px. Placed cards
do not auto-connect, card dragging suppresses text selection, and Delete removes
the selected card. The position arrows and always-visible Connections panel
were removed; a focused wire can be deleted with Delete. The palette and help
can be collapsed, and the editor surfaces use the active Hub theme variables.
Earlier table entries below describe the review's original implementation.

This review covers the main FastAPI entry point, Zigbee automation engine, dashboard and automation JavaScript, the three themes, and existing unit/browser tests. Findings below distinguish changes backed by a reproducible code path from ideas that still need live-device or usability testing. The linked guidance explains the expected benefit; it does not substitute for testing the Hub with users.

## Implemented in this review

| Finding and code evidence | Change | Evidence for benefit |
| --- | --- | --- |
| The default primary button used white text on `#8bd3ff` (`app/static/style.css`). Calculated contrast was **1.63:1**, below 4.5:1 for normal text. | Use `#07111b` text, calculated at **11.64:1**; keep theme-specific overrides. | [WCAG 2.2 contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) |
| Canvas ports were 20×20 CSS px and wires could only be removed by clicking a narrow stroke (`workspace.css`, `automation_graph.js`). | Ports are 28×28 px; a labeled Connections list supplies full-size Remove buttons. | [WCAG target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum), [keyboard access](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html) |
| Card position could only be changed by dragging, even though palette insertion and linking already had click alternatives (`automation_graph.js`). | Add click/keyboard move controls and arrow-key movement; snap all new/moved cards to the visible 23 px grid. | [WCAG dragging movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements), [NN/g drag-and-drop guidance](https://www.nngroup.com/articles/drag-drop/) |
| `graphLink()` accepted self-links, cycles, and incoming links to clock triggers until Save (`automation_graph.js`). | Reject those connections immediately with a specific message; retain server validation for full path semantics. | [NN/g error prevention](https://www.nngroup.com/articles/ten-usability-heuristics/), [error-message guidance](https://www.nngroup.com/articles/error-message-guidelines/) |
| Every inspector value change rebuilt all cards and fields; every automation poll replaced the list and palette (`automation_graph.js`). This can discard focus and interrupt edits. | Update only the changed card label; rebuild dependent fields with focus restored. Skip unchanged list/palette renders and restore focus after a status update. | [WAI-ARIA keyboard interface: persistence of focus](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/), [WCAG focus visible](https://www.w3.org/WAI/WCAG22/Understanding/focus-visible) |
| Port and container-detail filters relied on placeholder text (`index.html`). | Add programmatic labels without adding visible clutter. | [WAI labeling controls](https://www.w3.org/WAI/tutorials/forms/labels/), [WAI placeholder guidance](https://www.w3.org/WAI/tutorials/forms/instructions/) |
| Unchecked `JSON.parse(localStorage...)` at the start of `app.js` could prevent the entire UI from booting when one stored value was malformed. The Automations route also called `loadGraphAutomations()` twice. | Validate stored shapes, use safe defaults, and remove the duplicate load. | Direct startup code path; covered by a browser test with malformed stored values. |
| Home and Automations repeated their page title with a generic subtitle (`index.html`, `app.js`). | Hide those redundant subtitles while retaining contextual subtitles on other views. | [NN/g aesthetic and minimalist design](https://www.nngroup.com/articles/ten-usability-heuristics/) |

## Next improvements to evaluate

| Priority | Finding and evidence | Proposed work and decision needed |
| --- | --- | --- |
| High | Client-side link checks now catch simple impossible links, but `validate_graph()` still rejects more complex path/context mistakes only at Save (`automation_graph.js`, `graph_automation.py`). | Add inline path diagnostics that identify the offending cards. Test branching and saved-graph compatibility before extending validation. [NN/g error prevention](https://www.nngroup.com/articles/ten-usability-heuristics/) supports earlier feedback. |
| High | The inspector resolves an item's context from the **first** incoming edge, but the server evaluates **every** incoming path (`graphContext()` and `validate_graph()`). Joined flows can therefore show the wrong property/action choices. | Define whether joins are allowed; either show per-path context or validate that all incoming paths agree. Do not silently invalidate saved graphs. This is a code-path correctness issue. |
| High | `sendZigbeeAction()` calls `control.blur()` to let a later render update the card; `renderZigbee()` skips controls while an input remains focused (`zigbee.js`). | Preserve focus and update reported/draft values separately. Test keyboard control, delayed MQTT reports, and rejected commands. [WAI-ARIA focus persistence](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/) and [NN/g system status](https://www.nngroup.com/articles/visibility-system-status/) support this direction. |
| High | `_tick_clock_triggers()` fires only inside a 60-second window and marks a day fired before sending actions (`automation.py`). Offline minutes are skipped; a failed action is not retried that day. | Decide explicitly between skip, bounded retry, and catch-up policies, then expose that policy in the editor and status. Test restart, DST, disconnection, and partial action failure before changing execution semantics. |
| High | Login sets `secure=False` for the session cookie even when the Hub may be used behind HTTPS, and `/login` has no visible attempt throttling (`main.py`). | Add deployment-aware HTTPS cookie handling and a tested attempt-limit policy without breaking LAN HTTP logins. Audit trusted proxy headers first. [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) supports the `Secure` attribute on HTTPS; [OWASP authentication guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) covers login throttling. |
| Medium | `notify()` drops MQTT events when its bounded queue fills, but only catches `queue.Full` and gives no operator-visible count (`automation.py`). | Record dropped-event count and last occurrence in an automation health/status response. [Python Queue documentation](https://docs.python.org/3/library/queue.html#queue.Queue.put_nowait) confirms `put_nowait()` raises `Full`. |
| Medium | The shared `patchContent()` updates children by index (`app.js`). Reordering cards can reuse a DOM control for a different item. | Move to key-based reconciliation for dynamic service lists and add a focus/identity regression test. Measure affected flows first; current Zigbee cards already use an ID map. [WAI-ARIA focus persistence](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/) explains the impact. |
| Medium | Many labels and secondary controls use 10–11 px text, with further 9–10 px reductions on mobile (`workspace.css`, `themes.css`). | Test 200% text resize and narrow viewports across all themes; increase the smallest functional labels where they become hard to read, retaining a compact layout. [WCAG text resize](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html) provides the criterion. |
| Medium | Earlier timed rules can now be enabled/disabled/deleted but cannot be edited in the canvas (`automation_graph.js`). A naive conversion would change switch-off and occupancy behavior. | Design an explicit, previewable migration only after parity tests cover timers, repeated reports, occupancy holds, and multiple rules on one light. Avoid automatic conversion. |

## Validation approach

The browser checks cover desktop/mobile layout, snapped positions, click and keyboard movement, connection removal, focus after field edits and polling, and booting with malformed local settings. They verify behavior and geometry, not that every screen-reader/browser combination or real Zigbee device is usable; those need a hands-on pass before making broader changes.
