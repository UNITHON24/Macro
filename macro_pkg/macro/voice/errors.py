class AutomationCancelled(RuntimeError):
    """Raised when the operator activates PyAutoGUI's emergency stop."""


class GroundingError(RuntimeError):
    """Raised when a visible target cannot be identified unambiguously."""


class TransitionVerificationError(RuntimeError):
    """Raised when an action's expected screen transition is not observed."""


class ProfileError(ValueError):
    """Raised when a kiosk profile or requested menu option is ambiguous."""
