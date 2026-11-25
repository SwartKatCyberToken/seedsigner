"""Step names to Views, and a home-screen error Destination.

Does not collect text or run cryptography. Message views call these after
message_crypto.flow.advance. View imports stay inside the functions so the
view modules can import this file without a cycle.
"""

from seedsigner.message_crypto.errors import MessageCryptoError


def destination_for(step: str):
    from seedsigner.views.view import Destination

    if step == "notice":
        from seedsigner.views.message_views import MessageEncryptNoticeView
        return Destination(MessageEncryptNoticeView)
    if step == "alg":
        from seedsigner.views.message_views import MessageAlgorithmView
        return Destination(MessageAlgorithmView)
    if step == "keys":
        from seedsigner.views.message_views import MessageKeyListView
        return Destination(MessageKeyListView)
    if step == "fingerprint":
        from seedsigner.views.message_collect_views import MessageFingerprintView
        return Destination(MessageFingerprintView)
    if step == "input":
        from seedsigner.views.message_collect_views import MessageInputChoiceView
        return Destination(MessageInputChoiceView)
    if step == "review":
        from seedsigner.views.message_collect_views import MessageReviewView
        return Destination(MessageReviewView)
    if step == "run":
        from seedsigner.views.message_run_views import MessageExecuteView
        return Destination(MessageExecuteView)
    raise MessageCryptoError(f"unknown message step {step}")


def message_error(text: str, headline: str = "Cannot continue"):
    """Clear the message flow and show text. text must not contain secrets."""
    from seedsigner.controller import Controller
    from seedsigner.views.view import Destination, ErrorView, MainMenuView

    controller = Controller.get_instance()
    controller.message_flow = None
    controller.message_scanned = None
    return Destination(
        ErrorView,
        view_args=dict(
            title="Message",
            status_headline=headline,
            text=text,
            button_text="Home",
            next_destination=Destination(MainMenuView, clear_history=True),
        ),
    )
