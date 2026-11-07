"""Domain layer: pure business concepts and ports.

Must not import application, infrastructure, presentation, config, FastAPI, or any
operational/synchronization settings (retry, backoff, cache windows live in config).
"""
