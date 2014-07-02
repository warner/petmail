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
python setup.py safe_develop
./bin/petmail create-node
./bin/petmail start
./bin/petmail open
```

You can also unpack a release tarball, instead of using a git checkout.

The `safe_develop` command is shorthand for:

* `virtualenv venv`, which creates a self-contained virtual environment in
  the `./venv` directory. This virtualenv uses the system Python and stdlib,
  but none of the libraries installed to site-packages.
* `peep install -r requirements.txt`, which (mostly) safely installs
  Petmail's dependencies into the virtualenv. Safety not guaranteed (yet),
  but eventually this will do its best to obtain the "correct" versions of
  all dependencies before running any downloaded code.
* `setup.py develop`, which installs a `bin/petmail` and a link to the source
  tree into the virtualenv. Each time you run this `venv/bin/petmail`, it
  will import the current sources, so you don't need to re-install after
  modifying the source files.

The `./bin/petmail` script simply checks for the existence of the virtualenv
and delegates control to `./venv/bin/petmail`. You could run
`./venv/bin/petmail` directly, but it requires more typing.

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
./bin/petmail create-node NODE1
./NODE1/petmail start
./NODE1/petmail open
./bin/petmail create-node NODE2
./NODE2/petmail start
./NODE2/petmail open
```

### Overriding Dependencies

To test Petmail against alternate versions of its dependencies, you can
simply use `PYTHONPATH=/path/to/otherdeps ./bin/petmail`, and the extra
directories will be searched before the virtualenv's contents.

### Hints On Dependencies

Petmail's use of Twisted is straightforward: installing Twisted requires
zope.interface, and both have some optional C extension modules, but neither
have any deep dependencies on anything else.

Petmail gets its crypto from the "pynacl" package, which is a cffi-based
binding to the "libsodium" C library. This will compile libsodium during
installation, and then compile the python bindinds upon first import, both of
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

This may require root access, and may not be as safe as `safe_develop` (for
example, the "install" command does not know how to check hashes on
dependency tarballs). You might also try `pip install petmail` to download
the current release, or `pip install .` from an unpacked source tree. You can
also do any of these from within a virtualenv, or you could use `pip install
--user petmail` to install them to your home directory instead of site-wide.


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

## Dependency Verification

To keep the source tree small, Petmail's dependencies are not included.
`python setup.py safe_develop` fetches these tarballs from PyPI. However the
command (thanks to `peep`) verifies SHA256 hashes of the tarballs before
using them.

**(note: not available yet)** If you wish to avoid downloading additional
files during the build_deps process, use a "SUMO" source tarball, which
includes copies of the dependencies. You can also run `python setup.py
fetch-deps` to download and verify them, after which `safe_develop` will not
download anything.
