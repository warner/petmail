Petmail
=======

 https://github.com/warner/petmail


.. image:: https://travis-ci.org/warner/petmail.png?branch=master
   :target: https://travis-ci.org/warner/petmail

Petmail is a secure communication/file-sharing system. It is a reboot of my
earlier "Petmail" spam-resistant mail system (http://petmail.lothar.com/),
continuing the aims of that project but not sharing any code. It also draws
inspiration from Tahoe-LAFS, Dropbox, Pond/Panda, and others.

Status / Limitations
--------------------

Nothing works yet. I'm slowly building functionality to meet the aspirations
of this document.

What works so far:

* building, if you can get libsodium installed first (perhaps into the
  deps-venv that 'build_deps' creates).
* unit tests: `./bin/petmail test`
* creating two test nodes in the source directory, enabling their "local
  mailboxes", having them invite each other, sending a basic text message
  from one to the other, and dumping the incoming messages:

  * `make rebuild enable-local-mailbox connect`
  * `./bin/petmail -d n1 send-basic 1 hello`
  * `./bin/petmail -d n2 fetch-messages`

The web frontend (`petmail open`) is served, but is empty (actually it
contains non-functional leftovers from an earlier project).

The invitation mechanism only works with two nodes that live underneath the
same source tree: the real network protocol for invitations has not yet been
implemented.

The message-sending mechanism can only send to localhost, so the
communicating nodes must live on the same machine.

How To Run Petmail
------------------

To run from source, you will need Python (2.x) and the development headers
(python-dev). You will then build the dependencies, create and start a node,
and open the web-based control panel like so:

* `python setup.py build_deps`
* `./bin/petmail create-node`
* `./bin/petmail start`
* `./bin/petmail open`

Users are encouraged to run a pre-packaged application instead. Once you
start this application, use the menu item to open the control panel.

Theory Of Operation
-------------------

[this section contains forward-looking statements and is likely to contain
intentions rather than accomplishments]

Each Petmail node runs as a background application on your local computer.
All interaction takes place through a browser-based control panel, which you
can open by running `petmail open`.

Through the control panel, you can access the `Address Book`, which contains
contact information for everyone Petmail knows about. Use `Invitations` to
add people to your address book. You can exchange messages with people
through `Rooms`. You can also transfer files by dragging them into a Room.
Petmail also provides folder synchronization between computers (either your
own, or with other people).

To receive messages, you will need a `Mailbox`, which is a server that runs
all the time and has a publically-reachable IP address. You can run your own
mailbox, if you have a server like that, or someone else may run a mailbox
for you.

To store files, either to transfer to others or to synchronize with yourself,
you'll need a `Storage Server`. Again, this requires uptime and a public IP.
Petmail nodes can be configured to use S3 and other commodity storage systems
for this role, however some systems are only suitable for share-with-self
use, not share-with-others.

For More Information
--------------------

The `docs/` directory contains more information, including additional build
instructions and protocol specifications.

Thanks
------

Thanks for using Petmail!

Brian Warner
