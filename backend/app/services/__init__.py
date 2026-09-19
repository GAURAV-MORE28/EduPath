"""Deterministic services (design §7).

ARCHITECTURE_CONTRACTS.md §2: everything that is not one of the five LLM
agents is a deterministic service — Skill Normalizer, Evidence Verifier,
Skill Graph Service, Gap Engine, Resource Retriever/Ranker, Plan Validator,
Fallback Planner, Mastery Updater, Struggle Classifier, Reflection Validator,
Report Builder, Provenance Service, Trace Emitter. None are implemented yet;
each is added by the phase that owns it. This package exists so later phases
have a stable import location (`app.services.<name>`) from day one.
"""
