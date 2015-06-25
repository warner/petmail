# Invitations

Petmail agents learn about each other through `Invitations`. Each invitation
creates a pair-wise connection between the two nodes: an entry is added to
each node's addressbook, pointing to the other node. These entries enable
secure communication with the other agent, and by extension, the human who
owns that node/agent.

`Invitation Codes` are short strings that deliver the invitation. These codes
come from the [magic-wormhole](https://github.com/warner/magic-wormhole)
library, and are randomly generated. Most of the time, the code is generated
by one Petmail client, transcribed (spoken, IMed, emailed, etc) to the other
user, and then pasted into the second Petmail client. It is also possible for
the humans to decide on a code without the computers, then paste the same
code into both machines.

Once both Petmail agents have the shared code, the nodes will contact each
other through the magic-wormhole `Rendezvous Server`, exchange contact
details, and create the addressbook entries. The codes are single-use, so
they do not need to be memorized. They must remain secret only until the
invitation process is complete: afterwards they can be revealed without
consequence.

By default, these codes look like a number and two words, joined with
hyphens, like `9-tolerance-eyeglass`. Human-generated codes can be anything
that starts with a number and a hyphen. The only restriction is that they
must be typed exactly the same way into each computer. So the recommendation
is to use only lower-case letters. Literary phrases, famous quotes, and
well-known names should be avoided.


## Details

The magic-wormhole library is used to exchange long-term verification keys
and signed transport records. Note that the long-term verifying key is
different for each sender (so each pair of users will involve two verifying
keys).

The transport record lists the mailboxes used for inbound messages. It will
include: the mailbox descriptor string (including URL and mailbox pubkey),
the sender-specific STID and CID identifiers (see
[mailbox.md](./mailbox.md)), and the current rotating pubkey (used to provide
forward-secrecy).

When generating the transport record, each agent will remember several secret
values for themselves. This includes the CID for their correspondent, the
signing key they will use for outbound messages, and the private key they'll
use to decrypt inbound messages. These secrets will be stored in the
addressbook entry.

A future enhancement will add transport-level acknowledgments to the
protocol: after the wormhole process is done and a transport record is
received, the node will use the transport to send a "can you hear me" message
to its peer. Upon receipt of a response, the record will be marked as
"ACKed". The
[Two Generals's Problem](https://en.wikipedia.org/wiki/Two_Generals%27_Problem)
tells us that it is impossible to be sure that both sides agree that the
invitation process was successful, so the "ACKed" mark is merely extra
information that might help debug problems (if you see an addressbook entry
that is not ACKed, you should consider calling the other person and seeing if
they really got your invitation).
