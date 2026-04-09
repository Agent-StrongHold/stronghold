from typing import Protocol, runtime_checkable


@runtime_checkable
class IntentClassifier(Protocol):
    """Protocol for classifying user intents in queries."""

    async def classify(self, query: str) -> str:
        """Classify a single intent from a query.

        Args:
            query: The user's input query to classify

        Returns:
            A string representing the detected intent
        """
        ...

    async def detect_multi_intent(self, query: str) -> list[str]:
        """Detect multiple intents from a query.

        Args:
            query: The user's input query to classify

        Returns:
            A list of strings representing the detected intents
        """
        ...


class FakeIntentClassifier:
    """Fake implementation of IntentClassifier protocol for testing."""

    async def classify(self, query: str) -> str:
        """Classify a single intent from a query.

        Args:
            query: The user's input query to classify

        Returns:
            A string representing the detected intent
        """
        return "default_intent"

    async def detect_multi_intent(self, query: str) -> list[str]:
        """Detect multiple intents from a query.

        Args:
            query: The user's input query to classify

        Returns:
            A list of strings representing the detected intents
        """
        return ["default_intent"]
