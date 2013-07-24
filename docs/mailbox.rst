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

* http: this defines a set of POST and GET messages which enqueue, retrieve,
  and delete messages
* file: [for local development] this transport uses a local subdirectory, and
  stores one message per file
* smtp: messages are delivered as normal SMTP messages, consumed by a
  receiving node rather than by a human

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
