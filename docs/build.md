# Build Instructions

Petmail is written in Python. In addition to the python stdlib, it uses
Twisted and a few crypto libraries:

* Twisted > ??
* zope.interface
* pynacl-??
* python-scrypt-??

For developers who have these libraries already installed, there is no build
step.

The entry point is `./bin/petmail`. When run from a source tree,
`bin/petmail` automatically includes the petmail sources in `sys.path`.
Developers working on petmail may modify the sources and restart their node
without needing to copy or install anything.

The `python setup.py build_deps` command can be used to install a copy of
these dependencies in a local virtual environment named `./deps-venv`.
`./bin/petmail` will include the venv's site-packages in `sys.path`, before
the system site-packages directory (so the venv will override anything on the
system).

Petmail should run with just the stdlib and the contents of deps-venv. To
test this, run `./deps-venv/bin/python bin/petmail`, as the venv python will
ignore the system site-packages directory entirely.

## Packaged Application

For OS-X, Petmail is delivered as a standard application (a .dmg disk-image
which contains the app bundle, with visual instructions to drag it into the
Applications folder). When run, the app adds a menu item to the system menu
(on the top right corner of the screen). On first run, it also creates a node
for the user (in ~/Library/Application Support/Petmail) and starts it. It
also uses `petmail open` to open a control panel in the user's browser. The
menu can be used to re-open the control panel, or manually start/stop the
node. By default, the app is launched whenever the user logs in.

This app contains a copy of the deps-venv directory, into which the Petmail
source has been installed. The `bin/petmail` in the app is configured to put
this directory in `sys.path` first. It uses the system-supplied Python
executable.

## Dependency Verification

To keep the source tree small, Petmail's dependencies are not included.
`python setup.py build_deps` fetches these tarballs from PyPI. However the
command verifies SHA256 hashes of the tarballs before using them.

If you wish to avoid downloading additional files during the build_deps
process, use a "SUMO" source tarball, which includes copies of the
dependencies. You can also run `python setup.py fetch-deps` to download and
verify them, after which `build_deps` will not download anything.
