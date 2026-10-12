# Your instructions to the bot

Write here, in plain English, how you want the bot to work. Before it writes every video, the bot
reads this file and every document in `references/`, and follows them ahead of its own defaults
(YouTube's rules and the safety rules still come first). Development agents read them too.

**Two ways to steer:**

1. **Type** instructions in the list below.
2. **Upload a document** into `references/`: a PDF, a Word file (.docx), a text file or Markdown. On GitHub,
   open the `steering/references` folder, click **Add file > Upload files**, and commit. Long documents (a
   whole book) are condensed once into a page of rules, saved next to the file as `<name>.digest.md`; open it
   to see exactly what the bot took from your document, and edit it if you like (add `<!-- edited -->` at the
   top so it's kept). To switch a document off, move it into `references/off/`.

You can point at a document by name ("use references/titles-power-of-bad.md for titles"). Keep the newest
instructions at the top of the list. Settings that aren't about writing (voice, length, posting times,
feeds) live in `channel.toml`.

## Current instructions

- Pictures must match what George is saying at that moment, so they support the story instead of
  distracting from it. When no footage shows the idea, use a painting of it. (12 Oct)
- Add captions to every video. (12 Oct)
- Add suspense: open a question early and answer it at the end, end chapters on cliffhangers, and use
  short silences before reveals. Follow Mario Joos (`references/retention-mario-joos.md`). (12 Oct)
- Make long-form videos (about 8 to 12 minutes). Shorts are paused for now.
- One voice only: George, the older British narrator, reads everything, including the book quotes.
- Visuals are about the mind and the spirit (cosmos, light, candles, old books, water, mist,
  stillness, meditation), never wildlife unless the script is literally about an animal.
  Follow `references/visual-style.md`.
- Titles and thumbnail text use the negativity effect from *The Power of Bad* (Tierney and
  Baumeister). Follow `references/titles-power-of-bad.md`.
- YouTube know-how and do's and don'ts for long-form: `references/youtube-success-in-30-days.md`
  (notes from Brian Chesson's book).
