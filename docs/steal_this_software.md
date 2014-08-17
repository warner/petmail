# Steal This Software!

This document lists features and techniques in Petmail that could (should!)
be leveraged independently in other projects. I hope that Petmail, regardless
of its success or failure as an actual product, can have a positive influence
other projects. So please consider stealing these tricks in your own work.

## "nodedir" for Development and Deployment

Like we did in Tahoe-LAFS, each Petmail node stores all of its state in a
single "base directory" or "node directory" ("nodedir"), created by the
"create-node" command. The default location of the nodedir is under the
user's home directory, in a subdirectory named after the project itself
(~/.petmail, or perhaps "~/Library/Application Support/Petmail" on OS-X). But
it is trivial to put it elsewhere (using arguments in commands like "petmail
create-node NODEDIR" and "petmail start NODEDIR", and options in commands
like "petmail --basedir=NODEDIR open"), which makes it easy to spin up
multiple nodes on a single machine, for testing a "local testgrid".

In addition, Petmail puts a short script (also named "petmail") in the node
directory, which simply adds a "--basedir=" option and delegates to the
original "petmail" executable. It is easier to run "./NODEDIR/petmail
COMMAND" than to run "bin/petmail --basedir=NODEDIR COMMAND".

Since the script is the only executable in the nodedir (and it contains no
subdirectories), this also enables tab-completion when using multiple nodes
in a single parent directory. E.g. if the testgrid contains nodes "n1", "n2",
"n3", etc, then you can type "./n1 TAB TAB open RETURN" and will execute
"./n1/petmail open".

### Keeping All State in SQLite

Glyph recommended this to me many years ago: any machine-generated state
should be stored in a single-file database (i.e. SQLite), so it can be
manipulated atomically by the runtime code. I took this further and put all
configuration in the database too, so that the entire state of the node can
be captured by a single software version (git hash) plus the database
contents.

The downside is that you can't really use external tools to modify the node's
configuration (like how you can edit tahoe.cfg as a text file): basically
you, the program author, must provide code (subcommands of your main tool) to
configure everything. That's a drag. But the upside is that there's no
confusion about where the state or configuration lives, and there's no
hard-to-manage race between the user modifying their config and the program
modifying its state (both a atomic DB transactions).

For example, in Tahoe we'd kind of like to store the list of known servers in
a text file (one per line), because that'd be easy for a human to edit. But
the default mode is that the introducer client manages that list, so this
text file should be machine-modified. It only makes sense to edit this list
yourself if you've previously configured your node to *not* use the
introducer. So we'd wind up with one piece of code (the
connection-establishing client) that always reads from the list-of-servers
file, a separate piece of code (the introducer client) which maybe rewrites
this file, potential data-losing races if the user opens the file in an
editor while the introducer client is modifying it, concerns about if/how to
preserve comments and extra information during rewrites, and no good way for
the connection code to automatically learn that the server-list has changed.

This database could be encrypted to protect node state against passive
attackers who can read disk (perhaps from a backup) but not RAM. Petmail
doesn't do this (yet), but Pond does. The key would have to be provided when
first launching the node. Encrypting the whole database would be easiest
(http://sqlcipher.net/) but would interfere with CLI frontends retrieving the
access token (see below). This could be mitigated by encrypting only specific
rows or tables (basically everything but the access tokens), or by putting
access tokens in a separate place.

## Secure All-HTTP Frontend, Access Tokens, Event Channels

All Petmail frontends (both the CLI and the browser-based GUI) work through
HTTP APIs. These APIs all use HTTP POST requests with a JSON request body and
return a JSON response body. All of these APIS require an access token,
delivered as a property of the JSON request body (not as a URL query
argument, since URLs tend to leak through malware-URL-scanning features and
Referrer headers). The node (usually) only listens on the loopback interface
(127.0.0.1) so the "connection" doesn't traverse a real network and doesn't
require encryption to be safe. No cookies are used, ever, so there is no
ambient authority, which removes vulnerability to confused deputy and CSRF
attacks.

The frontend must somehow get an access token. CLI applications do this by
reading the token directly out of the database (if you can read the nodedir,
you can see the node's entire state anyways, so this does not really change
the privilege model).

The web frontend is launched with a CLI command ("petmail open"), which
unfortunately can only use HTTP GET (not POST). To avoid revealing the secret
access token in the URL, "petmail open" creates a single-use "opener token",
writes it into the database, then opens the browser to a redirection page,
adding the opener token in a queryarg. If the opener token is good, the node
interpolates the access token into the redirection page, which self-submits a
POST (with the access token as a hidden input field) to retrieve
"control.html", the single-page frontend app. The access token is also
interpolated into this control page, where it is retrieved by Javascript code
and submitted along with each API request. This way, the only secret that
appears in a URL should be expired by the time any external servers might
learn about it.

Most API calls trigger an asynchronous action on the node. They return
immediately, with a minimal "arguments were valid" success code. Most of the
information delivered to the frontend arrives through a single EventSource
channel (aka "SSE" Server-Sent Events). One API call creates the channel,
which returns an "event token" that is used to form the EventSource URL.
Other API calls subscribe and unsubscribe this channel to various message
types. This is used to notify the frontend about the consequences of its
requests (e.g. "invitation started"), as well as events triggered by other
nodes ("message received").

# Hash-Based Dependency Management

It is difficult to install (or worse, develop) software without making
oneself vulnerable to various attackers. These attackers can deliver "evil"
variants of the code you intended to run. The top-level installation can be
protected (i.e. it will successfully meet a policy of "I want to run the
software that everybody else is running", or "I want to run the software that
author X wants me to run") by using a cryptographic hash or public key as a
starting point. However most non-trivial software depends upon additional
libraries that come from other places. To avoid being infected by evil
variants of the dependencies, the build or install process needs to apply
cryptographic checks to them too.

Petmail attempts to use a model in which the Petmail author locks down the
exact contents of the dependencies. Downstream users are responsible for
getting the "right" copy of Petmail, then Petmail will ensure that it gets
the "right" copy of everything else (excluding Python and the rest of the OS,
both of which are equally vulnerable avenues of attack). It does this (albeit
not entirely successfully, yet) by using Peep to download specific claimed
versions of its dependencies, then checking hashes of these tarballs before
unpacking and installing them.

Petmail is intended to be self-contained (using Python and the OS as its
TCB), and run from a virtualenv that is only populated by Petmail's setup
code.
