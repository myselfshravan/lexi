# Visuals to add (2 minutes, big payoff)

Two images make this repo pop and drive shares. Drop them in this `docs/` folder,
then paste the snippets below into `README.md`.

## 1. The hero demo — `docs/demo.gif` (or `.mp4`)

The most viral visual: **you talking to the Echo Dot + the terminal streaming logs.**

- Point your phone at the Echo, say *"Alexa, open my lexi"*, ask a couple of things.
- Ideally split-screen (or cut) with `tail -f ~/alexa-lexi/server/logs/lexi.log` so viewers
  see the `▶ / ✓ 812ms` lines appear as you speak.
- Trim to ~15–20s. Convert to GIF (or keep the mp4) and save as `docs/demo.gif`.

Then add near the top of `README.md` (right under the title tagline):
```markdown
![Lexi in action](docs/demo.gif)
```

## 2. Optional evidence — `docs/cloudwatch-broken.png`

Supports the *hedged* "honest aside on hosting" in the blog — not a headline claim, just proof for the curious. Skip if you'd rather not lead with it.

- Alexa dev console → one of the (Alexa-hosted) skills → **Code → CloudWatch Logs**.
- Open the log group `/aws/lambda/<skill-id>` → screenshot the red banner:
  **"Log group does not exist … does not exist in this account or region."**
- Save as `docs/cloudwatch-broken.png`.

Then add it near the "honest aside" in `BLOG.md` (or the "Why self-hosted?" section of `README.md`):
```markdown
![CloudWatch: the runtime Lambda's log group was never created](docs/cloudwatch-broken.png)
```

---

Once both are in, `git add docs && git commit -m "add demo + cloudwatch screenshot" && git push`.
