"""IASL: the Intelligent Adaptive System Layer.

A deterministic, rule-based feedback loop that observes the OS concurrency layer and moves one
parameter (the admission depth limit) inside hard bounds. It never touches registration logic or
the database: nothing in this package may import app.registration_service, app.models,
app.database or app.seed (a test enforces this). See docs/iasl/ for the design.
"""
