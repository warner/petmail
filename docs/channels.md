# Channels

When two agents finish the invitation process, the result is a pair of
`Channels`, one in each direction. Each `Channel` is a unidirectional
connection from one agent to a second, enabling the transfer of "payloads".
The two paired channels (one outbound plus one inbound) to/from another agent
are managed on each end by a `channel record` which lives inside the
`addressbook entry`. Both are identified by the Channel Identifier `CID`. The
channel record contains enough information to send payloads via the outbound
channel, and to identify and decrypt payloads received on the inbound
channel.

## Channel Identifier

The Channel Identifier (`CID`) is a small integer, which points to an
addressbook entry and its embedded channel record. They are local to each
agent: two ends of a single channel will have unrelated CIDs. In Alice's
agent, her channels to and from Bob may use CID 123, whereas within Bob's
agent those two channels may use CID 456.

When code within Alice's agent wants to send a packet to Bob, it will bundle
the packet into a payload and submit the payload to her agent's `send()`
function with `to=123`. When that payload arrives at Bob's agent, Bob's
packet dispatcher function will be invoked with `from=456`.

## Packets

Payloads contain a variety of packets, each intended to be consumed by a
specific handler. Some are administrative and are consumed by the Agent
itself, such as the "new-channel-key" packet which updates the rotating keys
that provide forward-secrecy. Another administrative packet is the
"update-transport-record" packet which is used to add or modify the
recipient's transport records (e.g. when the sender adds a new mailbox).

Others are intended for delivery to the user who owns the Agent. The current
"basic" packet is a simple text message, displayed to the user, IM-style.
More sophisticated packet types will be added in the future.

## Payloads

The "payload" is JSON-encodeable object that contains some number of packets.
For each one, the packet type is used as the key, and the packet body is used
as the value. The payload is encrypted using the channel keys, and the
resulting encrypted message is delivered to the appropriate Transports.

## Transports

Each Agent listens on some number of "transports". Each one provides a way to
deliver encrypted payloads from one Agent to another. Most transports involve
some kind of queued message server, enabling messages to be sent even when
the recipient's agent is not running. Each time a Petmail user signs up with
a new Mailbox Server, they will add an additional Transport.

Each transport has a "delivery" side and a "retrieval" side. The outbound
channel record contains delivery information (typically a URL and some
cryptographic keys) for each transport used by the recipient: this gives the
sender enough information to get the encrypted payload to the right server.

The recipient uses the retrieval information to fetch the queued messages:
they will either poll the servers periodically, or establish a persistent
connection to receive immediate notification of new messages. The retrieval
information includes a URL and some cryptographic keys to ensure that nobody
else can retrieve the queued messages. Most of this information is stored in
the "mailboxes" table, not in the per-correspondent channel records, since it
is shared among all channels. However a small set of values are stored in the
inbound channel record, used to determine which channel a particular message
was delivered to.

Each channel message is delivered to all registered transports, providing
redundancy so the message will get through even if some of the transports are
broken. The recipient ignores duplicates.
