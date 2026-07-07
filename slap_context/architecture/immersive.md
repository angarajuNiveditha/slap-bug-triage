# Immersive — Team, Modules & Routing Guide

**Team:** Immersive (3D and AR/VR track under Yatin's Labs)
**Manager:** Yatin Grover
**Jira component:** `immersive` (id `14387`)
**Stack:** native iOS (Swift / Objective-C), native Android (Kotlin / Java), 3D SDKs, AR frameworks

⚠ **This skill file has less concrete grounding than the other four teams.** Reasons:
- **No repo cloned locally** — I can't mine class names, exceptions, or module structure the way I did for Backend (`edison`), BE-Labs (`dropsense` etc.), or DS (`slap-auto-qc-pipeline`).
- **Zero `immersive`-labelled bugs** in the 564-bug FLIPPI corpus we have on disk. Every routing signal below is inferred from the Yatin's Labs org chart the user shared, not from real bug titles.
- **No entry in `slap_context/architecture/repos.json`** for Immersive-owned repos.

Treat the contents of this file as team-lead org-chart notes, not as data-mined patterns. A follow-up should be to (a) clone the Immersive repos into `data/repos/`, (b) re-run `build_repo_skills.py`, and (c) rewrite this file from the mined class inventories the way the other four team files were rewritten.

---

## What Immersive owns

From the SLAP org chart, Immersive is Yatin's third track (alongside UI and Backend-Labs). It owns everything **3D, AR, VR, and native camera-based** on SLAP. Frontend and backend are both under Immersive here — this is a full-stack team.

### Frontend surface area (each owner reports to Yatin)

| Feature | Frontend owner |
|---|---|
| **3D SDK** — the reusable SDK for embedding 3D content in the RN app | Varun |
| **AR / VR** (native, `Sanvardith`) — the AR overlay engine | Hyzam |
| **Beauty VTO** — virtual try-on for beauty products (native try-on, not the RN one) | Hyzam |
| **Camera Filters** *(deprecated)* — filter overlays; kept for context, no active work | Hyzam + Varun |
| **3D Video Tool** — the tool for creating 3D video content | Varun |
| **3D Videos** — playback engine for 3D videos on SLAP *(ownership migrating to catalog team)* | Varun + Divyanshu |
| **Scale 3D** — the 3D scaling / rendering pipeline | Sourabh (with Varun oversight) |

### Backend surface area

**Sachin** owns 3D backend (also owns Sachin's other tracks in BE-Labs). Under Sachin:

- **Darshan** — model uploads, guardrails, compression pipelines (i.e. the ingestion + processing side of 3D assets)
- **Divyansh** — 3D videos orchestrator (the service that assembles and serves 3D video streams)

---

## Common Bug Routing Signals (inferred, not data-mined)

Because there are no `immersive`-labelled bugs in the corpus, these signals are heuristics based on the org chart. If you see one of these phrases in a bug, this team is the likely owner:

| Phrase / cue | Likely sub-area | Likely owner |
|---|---|---|
| "3D video not playing" | 3D Videos playback | Varun / Divyanshu |
| "3D SDK crash", "3D scene not loading" | 3D SDK | Varun |
| "AR overlay misaligned", "AR marker not tracking" | AR / VR | Hyzam |
| "VR mode broken" / "Sanvardith" | AR / VR native | Hyzam |
| "Beauty VTO not applying / mask wrong" | Beauty VTO | Hyzam |
| "Beauty try-on face detection failing" | Beauty VTO | Hyzam |
| "Camera filter broken" *(may be deprecated)* | Camera Filters | Hyzam + Varun |
| "3D video tool", "3D content creation" | 3D Video Tool | Varun |
| "Scale 3D pipeline failure" | Scale 3D | Sourabh |
| "3D model upload failing" | 3D backend | Darshan (under Sachin) |
| "3D asset compression pipeline" | 3D backend | Darshan |
| "3D video orchestrator down" | 3D backend | Divyansh (under Sachin) |
| Any bug containing "AR", "VR", "3D" as a primary noun in the title | Immersive generally | Yatin escalation |

---

## Boundary rules

### Immersive ↔ UI

Both teams work in native code. The rule:

> **Immersive owns anything that renders 3D geometry, does AR camera compositing, or runs on a specialised SDK (Sanvardith, Beauty VTO, 3D SDK).**
> **UI owns everything else — RN screens, standard native modules (auth, storage, permissions), 2D layout.**

If a bug title says `[iOS]` or `[Android]` but the failure is specifically about a 3D scene / AR overlay / Beauty VTO surface, it's still **Immersive**, not UI — the native platform is incidental. The `Sanvardith` codename is a strong Immersive signal.

### Immersive ↔ Backend-Labs

BE-Labs owns VTON as in "virtual try-on for clothes" (draping, avatar generation — the AI/ML side). **Immersive** owns VTO as in "Beauty VTO" — the native SDK that overlays a face mask for beauty products.

- "VTON gender mismatch" → BE-Labs (draping persona logic)
- "Beauty VTO mask misaligned" → Immersive (native camera SDK)

### Immersive ↔ Catalog team *(external to SLAP)*

The 3D Videos ownership is migrating **out of Immersive into the catalog team**. During the migration, bugs about 3D Videos may need dual-team attention. Currently Varun + Divyanshu still hold the line inside Immersive.

---

## Team roster (from org chart, no bug-corpus confirmation)

| Person | Role | Under | Sub-area |
|---|---|---|---|
| **Yatin Grover** | Manager | *(root)* | All of Immersive + also UI + Backend-Labs |
| **Sachin** | SDE-3 | Yatin | 3D backend + concurrent BE-Labs tracks |
| **Varun** | SDE-3 | Yatin | 3D SDK, 3D Video Tool, 3D Videos, Scale 3D (with Sourabh) |
| **Hyzam** | SDE-3 | Yatin | AR/VR (native), Beauty VTO, Camera Filters (deprecated) |
| Darshan | *(under Sachin)* | Sachin | 3D backend — model uploads, guardrails, compression |
| Divyansh | *(under Sachin)* | Sachin | 3D videos orchestrator |
| Sourabh | *(under Varun)* | Varun | Scale 3D |
| Divyanshu | *(under Varun)* | Varun | 3D videos (migrating to catalog) |

Yatin is the escalation target — `TEAM_MANAGERS["immersive"] = "Yatin Grover"` in `src/team_config.py`. The auto-escalation flow will assign to Yatin when no engineer has similar-bug history (which, given the empty corpus, is *always* today until immersive bugs start landing in Jira with the right component label).

---

## What is NOT Immersive

- RN screens, standard 2D layout, native modules that aren't 3D/AR/VR/camera-mask → **UI**
- Non-immersive VTON (draping clothes, styledrops avatar) → **Backend-Labs**
- Server-side APIs unrelated to 3D content → **Backend**
- Chat AI / ranking / content quality → **DS**

---

## Common title-prefix conventions (inferred)

- `[3D]`, `[AR]`, `[VR]` — Immersive
- `[Sanvardith]` — AR/VR native (Hyzam)
- `[Beauty VTO]` / `[BeautyVTO]` — Immersive (Hyzam)
- `[3D SDK]`, `[3D Video]`, `[Scale 3D]` — Immersive frontend
- `[Immersive]:` — team-tagged tickets

*(These are conventions I'd expect to see; the corpus has no confirmed examples yet.)*

---

## Follow-up to make this file "real"

Once Immersive repos are known and cloned to `data/repos/`, add them to `slap_context/architecture/repos.json` with entries like:

```json
{
  "name":         "<repo-name>",
  "team":         "immersive",
  "stack":        "swift" | "kotlin" | "cpp",
  "prod_branch":  "main",
  "purpose":      "...",
  "owns_features": ["3D SDK", "..."]
}
```

Then run `python3 build_repo_skills.py` to auto-generate per-repo skill files with real class inventories, and rewrite this file's "Common Bug Routing Signals" table from mined data.
