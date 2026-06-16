"""
Multi-agent pipeline for SLAP bug triage.

Astral (host_agent) coordinates the following sub-agents:
  - subagent_media       — process image/audio/video attachments → text findings
  - subagent_parser      — email + media findings → structured BugReport
  - subagent_embeddings  — retrieve top-K similar historical bugs from Jira
  - subagent_dedup       — decide whether the new bug is a duplicate
  - subagent_triage      — assign priority/severity

The host agent then hands the assembled result to agent_ticket_builder
to produce the final Jira ADF draft.
"""
