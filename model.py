"""
The part that talks to the language model.

Everything else in this project only needs an object with one method,
complete(system, user), that returns text. That keeps the model swappable and
lets the tests run with a stand-in, with no key and no network.
"""

import os

DEFAULT_MODEL = "claude-haiku-5-5"      # small and cheap is enough for this job


class MissingKey(Exception):
    pass


class ClaudeModel:
    """Calls the Claude API. Needs the 'anthropic' package and an API key in ANTHROPIC_API_KEY."""

    def __init__(self, model=None):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise MissingKey(
                "No API key found. Get one at https://platform.claude.com, then set it:\n"
                "  Mac or Linux:  export ANTHROPIC_API_KEY=your-key\n"
                "  Windows:       setx ANTHROPIC_API_KEY your-key   (then open a new terminal)"
            )
        try:
            import anthropic
        except ImportError:
            raise MissingKey("The 'anthropic' package is not installed. Run: pip install -r requirements.txt") from None
        self.client = anthropic.Anthropic()          # reads the key from the environment
        self.model = model or os.environ.get("ASK_MODEL", DEFAULT_MODEL)

    def complete(self, system, user):
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in message.content if block.type == "text")


class ScriptedModel:
    """A stand-in for tests: hands back prepared replies in order and remembers what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.asked = []

    def complete(self, system, user):
        self.asked.append((system, user))
        if not self.replies:
            raise AssertionError("ScriptedModel was asked more times than it has replies")
        return self.replies.pop(0)
