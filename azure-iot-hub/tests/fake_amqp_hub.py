"""A minimal local AMQP 1.0 endpoint that mimics just enough of Azure IoT
Hub's service-side AMQP behavior (CBS auth handshake + devicebound message
receipt) to give send_c2d_message real protocol-level test coverage.

Link-negotiation mechanics (dynamic source handling, credit-based dispatch)
are adapted from Apache Qpid Proton's own broker.py example -- not invented
from scratch -- since that's the officially maintained reference for this
part of the protocol. Only the CBS auto-reply and devicebound capture are
specific to this test fixture.
"""

import threading
import uuid
from collections import deque

from proton import Message, Terminus
from proton.handlers import MessagingHandler
from proton.reactor import Container


class _Queue:
    def __init__(self) -> None:
        self.messages: deque = deque()
        self.consumers: list = []

    def subscribe(self, consumer) -> None:
        self.consumers.append(consumer)

    def unsubscribe(self, consumer) -> None:
        if consumer in self.consumers:
            self.consumers.remove(consumer)

    def publish(self, message) -> None:
        self.messages.append(message)
        self.dispatch()

    def dispatch(self, consumer=None) -> None:
        targets = [consumer] if consumer else self.consumers
        for c in targets:
            while c.credit and self.messages:
                c.send(self.messages.popleft())


class FakeAzureIoTHubAmqp(MessagingHandler):
    """Accepts CBS put-token requests (always succeeds) and captures any
    message sent to /messages/devicebound for test assertions."""

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.acceptor = None
        self._queues: dict[str, _Queue] = {}
        self.received_devicebound_messages: list[Message] = []
        self._ready = threading.Event()

    def _queue(self, address: str) -> _Queue:
        if address not in self._queues:
            self._queues[address] = _Queue()
        return self._queues[address]

    def on_start(self, event) -> None:
        self.acceptor = event.container.listen(self.url)
        self._ready.set()

    def on_connection_opening(self, event) -> None:
        event.connection.offered_capabilities = "ANONYMOUS-RELAY"

    def on_link_opening(self, event) -> None:
        link = event.link
        if link.is_sender:
            dynamic = link.remote_source.dynamic
            address = str(uuid.uuid4()) if dynamic else link.remote_source.address
            link.source.address = address
            self._queue(address).subscribe(link)
        elif link.remote_target.type != Terminus.COORDINATOR:
            link.target.address = link.remote_target.address

    def on_link_closing(self, event) -> None:
        link = event.link
        if link.is_sender:
            address = link.source.address
            if address in self._queues:
                self._queues[address].unsubscribe(link)

    def on_sendable(self, event) -> None:
        self._queue(event.link.source.address).dispatch(event.link)

    def on_message(self, event) -> None:
        link = event.link
        message = event.message
        target_address = link.target.address

        if target_address == "$cbs":
            reply = Message()
            reply.correlation_id = message.correlation_id
            reply.properties = {  # type: ignore[assignment]  # proton's stubs mistype this as None
                "status-code": 202,
                "status-description": "Accepted",
            }
            self._queue(message.reply_to).publish(reply)
        elif target_address == "/messages/devicebound":
            self.received_devicebound_messages.append(message)

        event.delivery.update(event.delivery.ACCEPTED)
        event.delivery.settle()


class FakeHubServer:
    """Runs FakeAzureIoTHubAmqp in a background thread for the duration of a test."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        # port=0 would need OS-assigned port introspection, which proton
        # doesn't expose simply -- callers should pass a fixed free port.
        self.host = host
        self.port = port
        self.handler = FakeAzureIoTHubAmqp(f"{host}:{port}")
        self.container = Container(self.handler)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.container.run, daemon=True)
        self._thread.start()
        if not self.handler._ready.wait(timeout=5.0):
            raise RuntimeError("Fake AMQP hub did not start in time")

    def stop(self) -> None:
        self.container.stop()
        if self._thread:
            self._thread.join(timeout=5.0)
