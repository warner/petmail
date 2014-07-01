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

**Nothing works yet**. I'm slowly building functionality to meet the
aspirations of this document.

What works so far:

* building (if you can get libffi installed first): `setup.py safe_develop`
* unit tests: `./bin/petmail test`
* creating two test nodes in the source directory, enabling their "local
  mailboxes", having them invite each other, sending a basic text message
  from one to the other, and dumping the incoming messages:

  * `make rebuild enable-local-mailbox connect`
  * `./bin/petmail -d n1 send-basic 1 hello`
  * `./bin/petmail -d n2 fetch-messages`

The web frontend (`petmail open`) contains addressbook-manipulation UI, and a
just-barely-functional message-sending UI.

The invitation mechanism is functional but not complete. It does no
significant keystretching. The default configuration only works with two
nodes that live underneath the same source tree: there is no real-network
rendezvous server URL baked in yet.

The message-sending mechanism can only send to localhost, so the
communicating nodes must live on the same machine.

How To Run Petmail
------------------

To run from source, you will need Python (2.x), the development headers
(python-dev), and a C compiler. You will also either need a functional
python-cffi installation, or a copy of libffi somewhere that "pip install
cffi" can find it. Given these, you can then build the dependencies, create
and start a node, and open the web-based control panel like so:

* `python setup.py safe_develop`
* `./bin/petmail create-node`
* `./bin/petmail start`
* `./bin/petmail open`

Users are encouraged to run a pre-packaged application instead. Once you
start this application, use the menu item to open the control panel.

The node's working files are stored in a "basedir", which defaults to
`~/.petmail` in your home directory. Petmail does not modify any files
outside of this base directory. If you'd like to create a node somewhere
else, use `./bin/petmail create-node OTHERDIR`. The basedir includes a copy
of the `petmail` executable that knows where its basedir is, so once you've
created a node in OTHERDIR, you can run e.g. `OTHERDIR/petmail start` and
`OTHERDIR/petmail open` to launch the node and access its control panel.

(Note: the `safe_develop` command will install hash-verified dependency
tarballs into a local virtualenv named "venv/", then uses the setuptools
"develop" command to link the petmail sources into this virtualenv. The
`./bin/petmail` script looks in "venv/" for its source code.)


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
for you. Invitations are used to offer and add Mailboxes too.

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
