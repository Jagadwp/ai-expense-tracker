"""IMAP IDLE listener for real-time new-email detection (US-04).

IMAPClient's IDLE support is blocking — it holds the connection open and
waits, not something the rest of this app's asyncio code can do. So the
listener runs in a dedicated background thread. When new mail arrives, it
hands off to the app's asyncio event loop via run_coroutine_threadsafe to
run the actual sync — through the same Gmail API pipeline as the manual and
scheduled syncs (see app.sync_runner). IMAP here is only the trigger; it
never reads message content itself.
"""

import asyncio
import logging
import threading

from imapclient import IMAPClient

from app.config import Settings
from app.security import Encryptor
from app.store import Store
from app.sync_runner import NoGmailConnected, run_sync

logger = logging.getLogger(__name__)

# Gmail drops IMAP IDLE connections after ~30 minutes of inactivity; refresh
# the IDLE command a bit before that so the connection never goes stale.
IDLE_REFRESH_SECONDS = 25 * 60

# How long to wait before retrying after a connection error (network blip,
# Gmail restarting the connection, etc.) — the pipeline must survive these,
# not crash the whole listener.
RETRY_DELAY_SECONDS = 30


class ImapIdleListener:
    """Runs an IMAP IDLE loop in a background thread and triggers a sync on
    the main asyncio event loop whenever new mail arrives."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        encryptor: Encryptor,
        loop: asyncio.AbstractEventLoop,
    ):
        self._settings = settings
        self._store = store
        self._encryptor = encryptor
        self._loop = loop
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="imap-idle-listener", daemon=True
        )
        self._thread.start()
        logger.info("imap idle: listener thread started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Main loop for the background thread. Reconnects automatically on
        any error — a dropped connection must not kill the listener."""
        host, _, port_str = self._settings.gmail_imap_host.partition(":")
        port = int(port_str) if port_str else 993

        while not self._stop_event.is_set():
            try:
                self._listen_once(host, port)
            except Exception:
                logger.exception("imap idle: connection error, retrying in %ss", RETRY_DELAY_SECONDS)
                self._stop_event.wait(RETRY_DELAY_SECONDS)

    def _listen_once(self, host: str, port: int) -> None:
        with IMAPClient(host, port=port, ssl=True) as client:
            client.login(
                self._settings.gmail_imap_user,
                self._settings.gmail_imap_app_password,
            )
            client.select_folder("INBOX")
            logger.info("imap idle: connected and watching INBOX")

            while not self._stop_event.is_set():
                client.idle()
                try:
                    responses = client.idle_check(timeout=IDLE_REFRESH_SECONDS)
                finally:
                    client.idle_done()

                if responses:
                    logger.info(
                        "imap idle: %d event(s) received, triggering sync",
                        len(responses),
                    )
                    self._trigger_sync()

    def _trigger_sync(self) -> None:
        """Schedule a sync on the app's event loop from this background
        thread. Fire-and-forget: errors are logged inside _sync_and_log,
        not raised back into the IMAP thread."""
        asyncio.run_coroutine_threadsafe(self._sync_and_log(), self._loop)

    async def _sync_and_log(self) -> None:
        try:
            result = await run_sync(
                self._store, self._encryptor, "imap_idle", newer_than="1d"
            )
            logger.info("imap idle: sync completed: %s", result)
        except NoGmailConnected:
            logger.info("imap idle: sync skipped, no Gmail account connected")
        except Exception:
            logger.exception("imap idle: sync failed")
