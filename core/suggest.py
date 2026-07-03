"""
PromptChain — Preset Auto-Suggestion

Maps a rough task description to a matching (Prompter, Coder) preset pair via
whole-word keyword rules. Used by the task-input page to offer a one-click
"Apply" of the right presets; it only ever *suggests* — nothing is loaded
without the user clicking.
"""

import re

# Each rule: (label, keywords, (prompter category, name), (coder category, name)).
# Names must match presets/presets.json (tests/test_suggest.py enforces this).
# First match wins, so specific rules (languages, frameworks, domains) come
# before generic catch-alls (web page, python script).
SUGGESTION_RULES = [
    (
        "a bug fix / refactor",
        ("fix", "bug", "debug", "refactor", "crash", "broken", "traceback"),
        ("Debug & Refactor", "Bug Fix Brief"),
        ("Debug & Refactor", "Debugger & Refactorer"),
    ),
    (
        "a machine-learning task",
        ("train", "training", "classifier", "regression", "sklearn",
         "scikit-learn", "machine learning", "predict", "prediction", "neural"),
        ("Machine Learning", "ML Experiment Designer"),
        ("Machine Learning", "ML Engineer"),
    ),
    (
        "a browser game",
        ("game", "snake", "pong", "tetris", "breakout", "arcade", "platformer"),
        ("Games & Graphics", "Browser Game Designer"),
        ("Games & Graphics", "Browser Game Developer"),
    ),
    (
        "a scraping / automation task",
        ("scrape", "scraper", "scraping", "crawl", "crawler", "selenium",
         "beautifulsoup"),
        ("Data & Scripts", "Automation & Scraping"),
        ("Data & Scripts", "Python"),
    ),
    (
        "a SQL task",
        ("sql", "postgres", "postgresql", "mysql", "sqlite", "query", "queries"),
        ("Data & Scripts", "SQL Query Engineer"),
        ("Data & Scripts", "SQL"),
    ),
    (
        "a shell script",
        ("bash", "powershell", "shell script", "shell"),
        ("Systems & CLI", "CLI Tool Designer"),
        ("Systems & CLI", "Shell Scripting"),
    ),
    (
        "a Rust program",
        ("rust", "cargo"),
        ("Systems & CLI", "Systems Program Spec"),
        ("Languages", "Rust"),
    ),
    (
        "a Go program",
        ("golang", "in go", "with go", "using go"),
        ("Systems & CLI", "Systems Program Spec"),
        ("Languages", "Go"),
    ),
    (
        "a React app",
        ("react", "jsx", "tsx", "next.js", "nextjs"),
        ("Web Development", "React Specialist"),
        ("Web Development", "React"),
    ),
    (
        "a TypeScript project",
        ("typescript",),
        ("General", "Standard Prompt Engineer"),
        ("Languages", "TypeScript"),
    ),
    (
        "a Node.js backend",
        ("express", "node", "nodejs", "node.js"),
        ("Web Development", "Full-Stack Web"),
        ("Web Development", "Node.js / Express"),
    ),
    (
        "an API / backend",
        ("fastapi", "rest api", "api", "backend", "endpoint", "endpoints"),
        ("Web Development", "Full-Stack Web"),
        ("Web Development", "FastAPI"),
    ),
    (
        "a data-processing task",
        ("csv", "pandas", "dataframe", "excel", "etl", "data pipeline",
         "parquet"),
        ("Data & Scripts", "Data Pipeline Engineer"),
        ("Data & Scripts", "Data Analysis"),
    ),
    (
        "a CLI tool",
        ("cli", "command line", "command-line", "terminal", "argparse"),
        ("Systems & CLI", "CLI Tool Designer"),
        ("Systems & CLI", "CLI Tool Developer"),
    ),
    (
        "a test suite",
        ("pytest", "jest", "vitest", "unit test", "unit tests", "test suite"),
        ("Testing", "Test Spec Writer"),
        ("Testing", "Test Engineer"),
    ),
    (
        "a web page / app",
        ("html", "website", "webpage", "web app", "landing page", "frontend"),
        ("Web Development", "Single-File Web App"),
        ("Web Development", "Single-File Web App"),
    ),
    (
        "a Python script",
        ("script", "automate", "automation", "python"),
        ("Data & Scripts", "Python Script Engineer"),
        ("Data & Scripts", "Python"),
    ),
]


def _matches(task_lower: str, keywords) -> bool:
    """Whole-word match so e.g. 'go' can't fire inside 'logo' or 'good'."""
    return any(
        re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", task_lower)
        for kw in keywords
    )


def suggest_presets(task: str) -> dict | None:
    """
    Return {"label", "prompter": (category, name), "coder": (category, name)}
    for the first rule matching the task description, or None when nothing
    fits (in which case the defaults are the right call anyway).
    """
    if not task or not task.strip():
        return None
    task_lower = task.lower()
    for label, keywords, prompter, coder in SUGGESTION_RULES:
        if _matches(task_lower, keywords):
            return {"label": label, "prompter": prompter, "coder": coder}
    return None
