# CLAUDE.md

Project rules for `anchor-push`.

## Website & 3D Development Workflow

- **Brief & plan first**: Start new pages/sections with a one-paragraph brief (who, goal, 3-word feel) and plan multi-file changes before editing. Make one change at a time and keep everything else the same.
- **Skills & prompt pack**: Use `.claude/skills/new-section/SKILL.md` when adding/rebuilding sections, `.claude/skills/web-3d-section/SKILL.md` for Three.js/WebGL2/scroll-video work, `prompts.md` for reusable templates, and `docs/LAUNCH-CHECKLIST.md` before shipping.
- **Mobile, copy & keys**: Mobile-first at `390px`, `768px`, and `1440px` (no horizontal overflow, thumb-sized controls). Never use `lorem ipsum` or placeholder copy. Secret keys stay in `.env.local` (never in code, commits, or screenshots); public forms use RLS (insert-only, no public read).
- **Media & cinematic restraint**: Images in WebP (`<= 300 KB` hero `<= 1920px`, `<= 150 KB` cards `<= 1000px`, descriptive `alt`, `loading="lazy"` below hero); hero video `< 4 MB`, `<= 1080p`, no audio, `muted loop playsinline` + WebP poster. Use at most a slow hero visual + 1–2 cinematic moves, keep UI transitions `< 500ms` once, lazy-load 3D near viewport (`DPR <= 2`), and fall back to still images/plain stacked layouts on small phones, `prefers-reduced-motion`, or WebGL failure.
