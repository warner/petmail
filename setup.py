
import sys, os, hashlib, urllib2, subprocess, shutil
# the initial "setup.py safe_develop" doesn't require setuptools, and should
# work on a system that does not have it. But at the end of safe_develop, it
# runs "venv/bin/python setup.py develop", which *does* require setuptools.
# This conditional import is meant to work that second time around.
try:
    from setuptools import setup, Command
except ImportError:
    from distutils.core import setup, Command

import versioneer

commands = versioneer.get_cmdclass()

def run_command(args, cwd=None, verbose=False):
    print "running '%s'" % " ".join(args)
    try:
        # remember shell=False, so use e.g. git.cmd on windows, not just git
        p = subprocess.Popen(args, cwd=cwd)
    except EnvironmentError, e:
        if verbose:
            print "unable to run %s" % args[0]
            print e
        return False
    p.communicate()
    if p.returncode != 0:
        if verbose:
            print "unable to run %s (error)" % args[0]
        return False
    return True

def parse_deps_txt():
    deps = []
    for lineno0,line in enumerate(open("alldeps.txt", "r").readlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, hash, url = line.split()
        filename = os.path.basename(url)
        depfilename = os.path.join("support", "deps", filename)
        deps.append( (name, hash, url, filename, depfilename) )
    return deps

def hashfile(fn):
    h = hashlib.sha256()
    f = open(fn, "rb")
    while True:
        data = f.read(16*1024)
        if not data:
            break
        h.update(data)
    f.close()
    return h.hexdigest()

def verify_deps():
    for (lineno0,(name, hash, url, fn, depfn)) in enumerate(parse_deps_txt()):
        if not os.path.exists(depfn):
            print "must fetch", url, depfn
        gothash = hashfile(depfn)
        if gothash != hash:
            print "bad hash for %s (in %s)" % (name, depfn)
            print "got %s but wanted %s" % (gothash, hash)
            print "on alldeps.txt line %d" % (lineno0+1)
            print
            raise ValueError("bad hash on dependency tarball")

class FetchDeps(Command):
    description = "fetch+verify dependencies"
    user_options = []

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
        raise NotImplementedError("closed for maintenance")
        if not os.path.isdir("support/deps"):
            os.mkdir("support/deps")
        for (name, hash, url, fn, depfn) in parse_deps_txt():
            if not os.path.exists(depfn):
                print "fetching %s to %s" % (url, depfn)
                f = urllib2.urlopen(url)
                outf = open(depfn, "wb")
                while True:
                    data = f.read(16*1024)
                    if not data:
                        break
                    outf.write(data)
                outf.close()
        verify_deps()
        print "All dependencies fetched and verified"
commands["fetch_deps"] = FetchDeps


class SafeDevelop(Command):
    description = "safely install everything into a local virtualenv"
    user_options = []

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass

    def run(self):
        if os.path.exists("venv"):
            shutil.rmtree("venv") # clobber it
        # or add 'support' to sys.path, import virtualenv, munge sys.argv,
        # virtualenv.main(), replace sys.argv
        cmd = [sys.executable, "support/virtualenv.py", "venv"]
        if not run_command(cmd):
            print "error while creating virtualenv in ./venv"
            sys.exit(1)
        print "venv created"
        # TODO: or import support/peep.py, run peep.commands["install"](args)

        # peep uses "pip install --no-deps FILENAME" on hash-verified files,
        # but --no-deps is not honored when packages use setup_requires= . To
        # protect these downloads, we need to preemptively install them. peep
        # doesn't maintain order of requirements.txt lines, so we must run
        # peep multiple times. "pynacl" has setup_requires=[cffi] and
        # install_requires=[cffi,six], and cffi has an
        # install_requires=[pycparser], and six and pycparser have no
        # dependencies. So requirements1.txt contains [cffi], and
        # requirements2.txt has everything else.
        cmd = ["venv/bin/python", "support/peep.py",
               "install", "-r", "requirements1.txt"]
        if not run_command(cmd):
            print "error while installing dependencies (1)"
            sys.exit(1)

        # TODO: this isn't complete: I see a "Installed pycparser .egg" while
        # this is downloading pynacl.
        cmd = ["venv/bin/python", "support/peep.py",
               "install", "-r", "requirements2.txt"]
        if not run_command(cmd):
            print "error while installing dependencies (2)"
            sys.exit(1)

        cmd = ["venv/bin/python", "setup.py", "develop"]
        if not run_command(cmd):
            print "error while installing dependencies (3)"
            sys.exit(1)
        print "dependencies and petmail installed into venv"
        print "Now use './bin/petmail' to create and launch a node."

commands["safe_develop"] = SafeDevelop


setup(name="petmail",
      version=versioneer.get_version(),
      description="Secure messaging and files",
      author="Brian Warner",
      author_email="warner-petmail@lothar.com",
      license="MIT",
      url="https://github.com/warner/petmail",
      packages=["petmail", "petmail.mailbox",
                "petmail.scripts", "petmail.test"],
      entry_points={
          'console_scripts': [ 'petmail = petmail.scripts.runner:entry' ],
          },
      install_requires=["Twisted >= 13.1.0", "PyNaCl >= 0.2.3",
                        "magic-wormhole >= 0.3.0"],
      cmdclass=commands,
      )
