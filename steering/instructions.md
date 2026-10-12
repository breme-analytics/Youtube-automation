# Your instructions to the bot

Write here, in plain English, how you want the bot to work. Before it writes every video, the bot
reads this file and every `.md` file in `references/`, and follows them ahead of its own defaults
(YouTube's rules and the safety rules still come first). Development agents read it too.

You can point at a reference file by name ("use references/titles-power-of-bad.md for titles").
To add a new reference, drop a `.md` file into `references/`. To switch one off, move it into
`references/off/`. Keep the newest instructions at the top of the list below.

Settings that aren't about writing (voice, speed, video length, feeds) live in `channel.toml`.

## Current instructions

- Make long-form videos (about 8 to 12 minutes). Shorts are paused for now.
- One voice only: George, the older British narrator, reads everything, including the book quotes.
- Visuals are about the mind and the spirit (cosmos, light, candles, old books, water, mist,
  stillness, meditation), never wildlife unless the script is literally about an animal.
  Follow `references/visual-style.md`.
- Titles and thumbnail text use the negativity effect from *The Power of Bad* (Tierney and
  Baumeister). Follow `references/titles-power-of-bad.md`.
- Retention follows Mario Joos. Follow `references/retention-mario-joos.md`.
- YouTube know-how and do's and don'ts for long-form: `references/youtube-success-in-30-days.md`
  (my notes from Brian Chesson's book).
