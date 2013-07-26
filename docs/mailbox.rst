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

Each transport descriptor needs to convey three pieces of information:

* Reachability data for the mailbox. This is frequently a hostname/IP-address
  and a port number. Some transports have other forms of indirection, so this
  could instead be a Tor hidden-service (.onion) address, or a SMTP mailbox
  name (username@host), or a local directory name.
* Encryption pubkey for the mailbox. This is a 32-byte Curve25519 pubkey. All
  clients who share a mailbox will use the same pubkey. The intention is to
  conceal the ultimate recipient of each message from an eavesdropper
  watching the mailbox's inlet.
* Client Identifier. This is a 32-byte random string, unique to each client.
  Messages will contain this identifier inside the encrypted payload, so it
  will be visible to the mailbox service itself, but not to an eavesdropper.
  Mailboxes will maintain a table mapping client-identifier to the client,
  allowing each client to fetch only its own messages.

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
whatever she can glean from the source of the message. Transport descriptors
include the Curve25519 pubkey of the transport server, and messages are
encrypted using an ephemeral sending key.

When a Tor hidden service is used as a transport, an eavesdropper should
learn even less.

Wire Protocol
-------------

To deliver messages via the raw TCP transport, a TCP connection is
established to the mailbox's address and port. This connection can be used
for multiple messages. Each message is encapsulated as follows:

* A two-byte version indicator, "v1" (0x76 0x31)
* A netstring containing the message (decimal length, ":", message, "."). The
  body of the netstring is:
** 32-byte Curve25519 pubkey of the mailbox. Multiple nodes will share a
   mailbox: all their messages will use the same mailbox pubkey. The idea is
   to conceal the ultimate recipient of the message from an eavesdropper (but
   not from the mailbox itself).
** 32-byte ephemeral Curve25519 pubkey. For each message delivered to this
   transport, an ephemeral keypair is created. The message is encrypted with
   the NaCl "box" function, using this ephemeral private key and the
   mailbox's public key. The ephemeral public key is then attached to the
   message so the mailbox can decrypt it.
** 24-byte nonce, randomly generated
** Encrypted message body, including 32-byte MAC. Output of crypto_box().

The decrypted message body is as follows:

* A two-byte version indicator, "m1" (0x6d 0x31)
* 68-byte Encrypted Client Identifier, described below
* 32-byte Curve25519 pubkey of the recipient. This comes from the receiving
  client node's published transport record. Users who have multiple mailboxes
  will use the same pubkey everywhere.
* 32-byte Curve25519 ephemeral pubkey of the sender.

Each sender gets a different Encrypted Client Identifier. The mailbox will be
able to decrypt this to get the recipient's single Client Identifier. To
compute the ECI:

* create a random keypair A
* compute X = xor(CI, SHA256(scalarmult(privA, pubMailbox)))
* return "eci0"+pubA+X (4+32+32=68 bytes)

The mailbox will compute SHA256(scalarmult(privMailbox, pubA)) and XOR with
the ECI to retrieve the client's CI.

Each message involves the use of several Curve25519 keypairs. Many of these
are created just for the one message, and discarded afterwards.

* keyA: used to build the ECI. Unique per (sender,recipient) pair. Created by
  the recipient before creating the transport descriptor given to the sender
  during introduction. Protects the real CI until it is inside the mailbox.
  Lifetime is the same as the transport descriptor (potentially unlimited).
* keyB: used to conceal the ECI (and the ultimate recipient) from an
  eavesdropper. Created by the sender for each delivered message (sending the
  same message to multiple mailboxes will use multiple keyBs). Protects the
  message until it is inside the mailbox. Lifetime is a single transport.
* keyC: used to  ..

THINKING OUT LOUD

recipient knows secret A, computes X=f(A)
sender should get a value X
mailbox should get random B and Y=f(X,B)
mailbox knows secret C
mailbox should compute g(B,C,Y) to get constant Z, maps Z to client

recipient has one A, gA
recipient picks B,gB for each sender
recipient sends ... to mailbox, mailbox computes CI, registers with recipient
sender given ...
sender picks C,gC for each message
mailbox has one D,gD
mailbox given gC, C*gD*..
mailbox computes CI= ...

S1
 sender gets Y, 
 S1Ta -> CI
   sender computes S1gM
   sender gives Y
   mailbox computes X=MgS1, CI=xor(X,Y)
 S1Tb -> CI
S2
 S2Tc -> CI
 S2Td -> CI

 (gM)   =   (M)

box(pubTo, privFrom, msg) = "b0"+pubTo+pubFrom+nonce+boxed = 2+32+32+24+msg+32
sign(from, msg) = "s0"+pubFrom+signed = 2+32+msg+64


C: receiving client identifier (sender must not learn/distinguish)
A: sender secret (client+sender can know, mailbox must not learn/distinguish)
B: per-message (mailbox can know)
M: mailbox secret (only mailbox knows, everyone can distinguish)

mailbox should wind up with f(C,M)
aim for (AB+1 - AB)*MC
    (AB+1)*MC - ABMC
    sender knows A,B, ACM, AM, not C, not CM
    sender can build ABCM,
    mailbox can safely be told AB, BCM, ABCM
    mailbox can apply M, unlike anyone else. So it adds or multiplies by M.
     sender gives AB, ABCM to mailbox
     AB(1+CM)

or (AB+1 - AB)*(M+C)
