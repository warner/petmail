# Build Instructions

Petmail is written in Python. In addition to the python stdlib, it uses
Twisted and a few crypto libraries:

* Twisted > 14.0.0
* pynacl-0.2.3
* python-scrypt-??

## Developers: Running From Source

If you want to hack on Petmail's source code, you'll need to run from a
source checkout. The following sequence should get you running:

```
git clone https://github.com/warner/petmail.git
cd petmail
virtualenv venv
source venv/bin/activate
pip install -e .
petmail create-node
petmail start
petmail open
```

You can also unpack a release tarball, instead of using a git checkout.

### Using Multiple Nodes

For personal use, you will only need a single Petmail node. To support this,
most Petmail commands (in particular `create-node`, `start`, and `open`)
default to using `~/.petmail` as their node base directory.

But to perform local testing, you may need to run multiple nodes at the same
time (and have them speak to each other). All Petmail commands allow you to
override the node-dir, but you really only need to do this for `create-node`,
because the new node-dir will include a wrapper for the `petmail` command
that has its node-dir baked in. So the following is an easy way to launch two
independent nodes:

```
petmail create-node NODE1
./NODE1/petmail start
./NODE1/petmail open
petmail create-node NODE2
./NODE2/petmail start
./NODE2/petmail open
```

### Overriding Dependencies

To test Petmail against alternate versions of its dependencies, you can
simply use `PYTHONPATH=/path/to/otherdeps petmail`, and the extra directories
will be searched before the virtualenv's contents. Or install the other deps
into the virtualenv (perhaps with `-e`).

### Hints On Dependencies

Petmail's use of Twisted is straightforward: installing Twisted requires
zope.interface, and both have some optional C extension modules, but neither
have any deep dependencies on anything else.

Petmail gets its crypto from the "pynacl" package, which is a cffi-based
binding to the "libsodium" C library. This will compile libsodium during
installation, and then compile the python bindings upon first import, both of
which require access to a C compiler (and the python development headers). To
install the (Python) cffi package, the libffi C library must first be
installed, and its headers must be available. On Debian-like systems, install
the "libffi-dev" package. On OS-X with Homebrew, install "libffi", but you
may need to symlink the
/usr/local/Cellar/libffi/VERSION/lib/pkgconfig/libffi.pc file into
/usr/local/lib/pkgconfig/ for it to be found at build time.

## Enthusiastic Users: Installing From Source

If you're keen on Petmail and want slightly more permanence, or if you want
to make Petmail available to other users on your unix-like system, you can
install it:

* `python setup.py install`

This may require root access. You might also try `pip install petmail` to
download the current release, or `pip install .` from an unpacked source
tree. You can also do any of these from within a virtualenv, or you could use
`pip install --user petmail` to install them to your home directory instead
of site-wide.


## Normal Users: Running From A Packaged Application

**[this section is aspirational, not factual]**

For OS-X, Petmail is delivered as a standard application (a .dmg disk-image
which contains the app bundle, with visual instructions to drag it into the
Applications folder). When run, the app adds a menu item to the system menu
(on the top right corner of the screen). On first run, it also creates a node
for the user (in ~/Library/Application Support/Petmail) and starts it. It
also uses `petmail open` to open a control panel in the user's browser. The
menu can be used to re-open the control panel, or manually start/stop the
node. By default, the app is launched whenever the user logs in.

This app contains a copy of the virtualenv, into which the Petmail source has
been fully installed, and uses the system-supplied Python executable.
