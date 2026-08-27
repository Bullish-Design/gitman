# Project 34 — adopt pyjutsu 0.19

Gitman runs against pyjutsu 0.15.0 / jj-lib 0.42.0. Pyjutsu is now at 0.19.0 / jj-lib 0.44.0,
plus three unreleased commits on `HEAD`. This project moves gitman onto the new engine.

## Documents

| File | Holds |
|---|---|
| [01-BUILD-AND-VALIDATE.md](01-BUILD-AND-VALIDATE.md) | Build the wheel, install it, and measure the damage. **Do this first.** |
| [02-REFACTOR-GUIDE.md](02-REFACTOR-GUIDE.md) | The nine refactor lanes, in order. |

## Order of work

1. Read `01-BUILD-AND-VALIDATE.md` end to end. Then run it.
2. Produce `BASELINE.md` (the guide tells you what goes in it).
3. Read `02-REFACTOR-GUIDE.md`. Work the lanes in the given order.

Do not start lane 1 until `BASELINE.md` exists. The baseline decides which lanes are
urgent and which are already green.

## Escalation points

Three decisions are not yours to make alone. The guides mark each one **DECISION**:

- The pyjutsu version string to build (`01`, step C).
- Lightweight or annotated release tags (`02`, lane 3).
- Whether gitman pins `immutable_heads()` in repo config (`02`, lane 6).

Bring these to the repository owner with your evidence. Do not guess.
