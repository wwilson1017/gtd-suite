# Build a deck

Save the returned template as `index.html`. Its source filename is `deck.html`.

## House rules

One `index.html`, plus media files beside it in the same folder. Use relative
paths, inline CSS and JavaScript, and system fonts. No CDN, remote dependencies,
embedded fonts or inline binary media: the deck must work offline.

Keep the 1600 by 900 stage (16:9) and fit-to-viewport engine. One idea per slide,
big type, short headings, few lines. Split crowded slides instead of shrinking
type. Use readable contrast, useful image alt text and a clear closing action.
Preserve arrow keys, clicker controls and fullscreen.

## Build and check

1. Copy the template, set the HTML title and replace the demo `<section>`s in
   `#stage`. Keep the stage, navigation and script. The six layouts are title,
   statement, bullets, image + text, two columns and closing. Each section is
   one slide. Replace the SVG placeholder with `<img src="photo.jpg" alt="...">`.
2. Put media beside the HTML. Video: `<video src="clip.mp4" controls
   preload="metadata"></video>`; it pauses when you leave its slide.
   `<aside class="notes">` holds hidden notes, still public in the source.
   Never include private information or credentials. Optional `class="step"`
   reveals a point on advance; Previous reverses reveals first.
3. Check every slide in a browser if you can: media, wrapping, contrast and
   controls. Console `deckCheck()` returns overflowing slide numbers or `[]`;
   inspect visually too. Say if you could not visually check it.
4. Right/Down, PageDown, Space or Enter advance; Left/Up, PageUp or Backspace
   go back. Clickers send these keys. Home/End jump to the ends; `#3` opens
   slide 3 and reload keeps the slide. F toggles fullscreen when permitted;
   F11 uses browser fullscreen. B or period blanks; N toggles large numbers.
   Mouse movement shows buttons; touch swipes navigate.

## Publishing

**One HTML file, no media files:** call `site_publish` with full HTML as
`content`, `format: "html"` and `title`. Or POST that JSON to the connected
agent link with `?cmd=PUBLISH`. Return `page.address`; retain `page.id`.

A deck with video needs "Own address for each page" in Settings. If SITE_SYNC refuses,
ask the person to turn it on.

**Folder with media:** use `site_sync` or POST `?cmd=SITE_SYNC`:

1. Send the complete `manifest`, including `index.html`: entries are
   `{path, size, sha256}` (relative path, exact byte size, lowercase hex SHA-256).
   Include only finished deck files. For creation, send a stable unique
   `client_ref`, reused on retries. Optional: `title`, `name`.
2. Retain the returned `site.id`. For every `missing` entry, find the file by
   `sha256`; PUT its raw bytes to `missing[].put.url` with its
   `missing[].put.headers`. Check upload success. Never send the agent link
   to an upload URL.
3. Call again with the same manifest and site id until `status` is `published`.
   An empty `missing` list alone is not success. Return `site.address`.

Updates reuse `id`, keeping the same address. Tools take `id`; commands use
`?cmd=PUBLISH&id=...` or `?cmd=SITE_SYNC&id=...`. Sync sends the entire desired
manifest, unchanged files included; only missing hashes need uploads.
Recalculate sizes and hashes after edits. Reload after updates: a page load
during publication can mix versions. Check the published address if possible.

## Limits

Read the connected link's [HELP guide](?cmd=HELP), under `limits`: `page_bytes`,
`site_bytes`, `storage`, `files_per_site`, `request_bytes`. Use these current
account limits; `site_publish` also describes its MCP request limit. Check
HELP's confirmation and expiry rules.

If refused as too big, shrink videos to 1080p H.264 and photos to 1,600 px on
their longest edge, keeping aspect ratio without upscaling. Keep originals
outside the deck folder. Check quality, rebuild the manifest and try again.
If still over, explain the limit and ask to reduce or split the deck.

## Once-only skill offer

After the first deck is published, offer once only if this AI can install
skills: Claude Code, Codex CLI, or an agent with a shell that reads SKILL.md
folders. Chat apps (claude.ai, ChatGPT) never get the offer, even with code tools.

Check history and durable task memory first. Skip if already offered or
installed, or if uncertain. Offer only if you can retain a record across sessions:

“Would you like me to install the full deck skill for future presentations?
The command is `npx skills@latest add wwilson1017/skills`.”

Record the offer in durable task memory, even on decline or no reply. Never
offer it twice. Run the command only if the person explicitly says yes;
silence and reading this guide do not authorize installation.
