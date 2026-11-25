# Feature: currency-and-video-material

Locator: `odd/tasks/currency-and-video-material.md` · Engram mirror: `odd/currency-and-video-material/tasks` (PENDING: Engram refused writes with `project_transition_conflict`; waiting for the user to choose the project key)

## Objective
1. Show prices as bolivianos (Bs) everywhere users read them, by relabeling only (no conversion, no exchange rate).
2. Prepare the source material for the NotebookLM video about integrating an agent bot into a system.

## Authorized scope (user, 2026-11-25: "solo cambia la etiqueta y anda preparando todo para empezar con el video")
- Currency: label/format only. Stored numbers stay untouched. Touches web list and form hint, bot formatting, Slack alert wording, assistant instruction, and their tests.
- Video material: outside the repo, in `E:\USUARIOS\Desktop\video-proyecto`. No push, PR or merge without the user's explicit OK.

## Tasks
- [x] T1 — Currency relabel to Bs. Branch `feat/currency-bolivianos`, commit `ef8c54c`. Route: delegated writer (2+ non-trivial files across frontend and backend). Test-first: RED observed (pytest 25 failed, vitest 2 failed), GREEN. The CatalogList/ProductForm test edits and the assistant-instruction test have no separately observed RED. Parent spot check: pytest 465 passed, vitest 66 passed. Native review (user granted consent): lineage `review-96eb06ce3e25f91e`, medium, 159 lines, 1 lens `review-reliability` → APPROVED, acknowledged, authority burned. Two informational suggestions, not acted on: `formatPrice` depends on the runtime's ICU data for es-BO, and the welcome text "(Bs)" in the `/productos` line has no assertion.
- [x] T2 — Video source document (Markdown), architecture diagram, and a README on how to use it with NotebookLM. Route: delegated writer (broad repo reading, outside the repo). Files in `E:\USUARIOS\Desktop\video-proyecto`: `fuente-notebooklm.md`, `arquitectura.md`, `README-video.md`. Fresh screenshots are NOT part of T2: they need the Bs change deployed, and the bot/Slack shots come from the user.
- [ ] T3 — Fresh screenshots after T1 is deployed (web by Claude via browser, bot and Slack by the user).

## Checks
- Backend: `backend/venv/Scripts/python.exe -m pytest -q`. Frontend: `npx vitest run` and `npm run build` in `frontend/`.

## Progress / Evidence
(none yet)
