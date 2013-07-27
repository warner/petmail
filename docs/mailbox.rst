Mailboxes
=========

To receive messages, each client must contract with at least one `mailbox`
service. This is a publically-reachable server with good uptime, that is
willing to store incoming messages later retrieval by the client. Mailboxes
allow clients to receive messages despite not being online all the time, and
living behind a NAT box.

Each mailbox has a `transport descriptor` string that describes how other
nodes should deliver messages to it. This is shaped like a URL, with a type
identifier string, followed by a colon, followed by the transport details.

Client nodes can provide their own mailbox. This is most useful for
development, however it can be used for production when the transport
provides NAT-traversal facilities, or when the client has a public IP
address.

Clients may advertise mailboxes with transport types that are unrecognized by
other clients. Some transports offer realtime confirmation of delivery, while
others are high-latency send-and-hope. Senders may elect to deliver multiple
copies of their message in parallel, and receivers must tolerate duplicates.


Transport Types
---------------

The following transports are defined or planned:

* tcp: a special wire protocol (defined below) is used on a simple TCP
  connection.
* http: this defines a set of POST and GET messages which enqueue, retrieve,
  and delete messages
* file: [for local development] this transport uses a local subdirectory, and
  stores one message per file
* smtp: messages are delivered as normal SMTP messages, consumed by a
  receiving node rather than by a human

Each transport descriptor needs to convey four pieces of information:

* Reachability data for the mailbox. This is frequently a hostname/IP-address
  and a port number. Some transports have other forms of indirection, so this
  could instead be a Tor hidden-service (.onion) address, or a SMTP mailbox
  name (username@host), or a local directory name.
* Encryption pubkey for the mailbox. This is a 32-byte Curve25519 pubkey. All
  clients who share a mailbox will use the same pubkey. This is used to
  encrypt the outer message, which will be decrypted by the mailbox. The
  intention is to conceal the ultimate recipient of each inner message from
  an eavesdropper watching the mailbox's inlet.
* Client Identifier. This is a 32-byte string, unique to each client.
  Messages will contain this identifier inside the outer-encrypted payload,
  so it will be visible to the mailbox service itself, but not to an
  eavesdropper. Mailboxes will maintain a table mapping client-identifier to
  the client, allowing each client to fetch only its own messages.
* Client Pubkey: a 32-byte Curve25519 public key. This will be used to
  encrypt the inner message, and will be decrypted by the recipient.

Multiple recipient nodes will share a mailbox service. Each will have a
distinct client identifier and client pubkey, but their transport
reachability data and mailbox pubkey will be the same.

Multiple mailbox services could share the same reachability address. Their
messages would be distinguished by the mailbox pubkey.

Clients can use multiple mailbox services. All four components of the
transport descriptor will be different, including the client pubkey.


Renting an Inbox
----------------

Clients must generally arrange to rent inbox space. The process for making
these arrangements is up to the individual service provider. Regardless of
how inbox service is obtained, the result is always an `inbox offer string`.
This short string should be pasted into the client node's Inbox Control
Panel. The node will then generate a transport descriptor for the inbox and
update all addressbook contacts with the new coordinates. New invitations
will include the updated descriptors.

The inbox provider is automatically added to the addressbook. They are given
the ability to deliver messages to the user. This channel allows the provider
to inform the user about service changes, and to discuss payment.

The inbox provider may find it necessary to change the transport coordinates
of the user's inbox. An additional channel, managed internally by the client
node, will receive and process these messages without user involvement.

Retention Periods
-----------------

Mailboxes are for temporary storage of inbound messages. Client nodes are
expected to retrieve their messages every few days, after which the mailbox
can delete the temporary copy. Mailboxes are allowed to delete even unread
messages after a while: the exact duration should be specified as part of the
contract (and displayed in the client UI), but is expected to be a few days
or weeks.

Transport Security
------------------

All Petmail messages are encrypted by node-to-node Curve25519 keypairs.
Messages sent to a transport are additionally encrypted by a
transport-specific key, so that an eavesdropper cannot distinguish the final
recipient of the message. Eve should only learn the intended transport, and
whatever she can glean from the source of the message (e.g. source IP address
or timing information). Transport descriptors include the Curve25519 pubkey
of the transport server, and messages are encrypted using an ephemeral
sending key.

When a Tor hidden service is used as a transport, an eavesdropper should
learn even less.

Anonymity
---------

The current protocol provides limited unlinkability. A mailbox cannot use the
contents of the message it sees to determine which sender provided it. Of
course, senders must disguise their transport address to take full advantage
of this (e.g. by sending through Tor).

A future version of this protocol should provide the following unlinkability
properties:

1: The mailbox cannot distinguish which sender provided a message (from the
   contents of the message.. they still might discern source IP address,
   etc). The mailbox can compute a recipient identifier, to know how to route
   the message, which will the the same no matter which sender created it.
   Two successive messages from the same sender cannot be identified as such.
2: Two senders cannot distinguish whether their transport descriptors refer
   to the same recipient or not, except for the shared mailbox addressing
   information. If Alice and Bob are senders, Carol and Dave are two
   recipients who rent mailboxes from the same host, then Alice gets two
   descriptors AC and AD, and Bob gets BC and BD. When Alice and Bob compare
   their descriptors, they should not be able to distinguish whether AC+BC go
   to the same person, or AC+BD. Alice herself cannot tell if AC+AD go to
   different people or the same person.
3: The recipient is not required to communicate with the mailbox to add each
   new sender, but can create new descriptors herself.
4: The sender can produce any number of messages without needing to acquire
   new tokens or information from the recipient.
5: The mailbox can determine the recipient of a message in constant time,
   rather than iterating through the full list of registered recipients
   looking for a match.

I don't yet know of a protocol that can satisfy these conditions. Tthere are
a number of simpler protocols that provide a subset:

* Give each sender the (same) client identifier, each sender includes the
  identifier in their message. This provides 1/3/4/5, but not 2. This is
  the current protocol.
* Register a different client identifier for each sender. Senders include the
  identifier in their message. This provides 2/4/5 but not 1 or 3.
* Give each sender a big list of single-use tokens, each of which is a
  randomly encrypted copy of the client identifier, using the mailbox's
  public key. This would provide 1/2/3/5 but not 4.

I expect a complete protocol would involve the senders getting
differently-blinded copies of the client identifier, then blinding these
tokens themselves for each message they send. It may be necessary to give up
on #5 (mailbox efficiency) to achieve the other four.

Wire Protocol
-------------

To deliver messages via the raw TCP transport, a TCP connection is
established to the mailbox's address and port. This connection can be used
for multiple messages, concatenated together (i.e. the connection can be
nailed up and messages delivered later). Each message is encapsulated as
follows:

* A two-byte version indicator, "v1" (0x76 0x31)
* A netstring containing the message (decimal length, ":", message, "."). The
  body of the netstring is:

  * 32-byte Curve25519 pubkey of the mailbox. Multiple nodes will share a
    mailbox: all their messages will use the same mailbox pubkey. The idea is
    to conceal the ultimate recipient of the message from an eavesdropper
    (but not from the mailbox itself).
  * 32-byte ephemeral Curve25519 pubkey (outer key). For each message
    delivered to this transport, an ephemeral keypair is created. The message
    is encrypted with the NaCl "box" function, using this ephemeral private
    key and the mailbox's public key. The ephemeral public key is then
    attached to the message so the mailbox can decrypt it.
  * 24-byte nonce, randomly generated
  * Encrypted outer message body, with 32-byte MAC. Output of crypto_box().

The mailbox decrypts the message body to obtain the following inner message:

* A three-byte version indicator, "ci1" (0x63 0x69 0x31)
* 32-byte Client Identifier
* the inner message:

  * A two-byte version indicator, "m1" (0x6d 0x31)
  * 32-byte Curve25519 ephemeral pubkey (inner key) of the sender.
  * 24-byte nonce
  * encrypted inner message body

The mailbox uses the Client Identifier to locate the client's queue, then
stores the inner message in that queue.

Client Flow
-----------

The recipient contacts the mailbox and retrieves any queued messages intended
for its client identifier, using a protocol that depends on the mailbox type.
The client then instructs the mailbox to delete the queued messages. If the
client maintains multiple client identifiers with the same mailbox service,
it must retrieve each set of messages separately. Each retrieved message is
associated with exactly one client identifier.

The recipient must maintain a table that maps from (mailbox+CI) to a keypair.
This pubkey will be the same one as in the sender's mailbox descriptor. The
recipient uses the matching privkey, and the ephmeral pubkey in the message,
to decrypt the body.
