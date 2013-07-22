
import sys, os, hashlib, urllib2, subprocess, shutil
from distutils.core import setup, Command

def run_command(args, cwd=None, verbose=False):
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

class BuildDeps(Command):
    description = "build dependencies"
    user_options = []

    def initialize_options(self):
        pass
    def finalize_options(self):
        pass
    def run(self):
        if os.path.exists("venv"):
            shutil.rmtree("venv") # clobber it
        cmd = [sys.executable, "support/virtualenv.py",
               "--distribute", "--never-download",
               "deps-venv"]
        if not run_command(cmd):
            print "error while creating deps-venv"
            sys.exit(1)
        print "deps-venv created"
        verify_deps()
        for (name, hash, url, fn, depfn) in parse_deps_txt():
            cmd = ["deps-venv/bin/pip", "install", depfn]
            if not run_command(cmd):
                print "error installing %s" % name
                sys.exit(1)
        print "deps installed into deps-venv"

commands = {
    "fetch_deps": FetchDeps,
    "build_deps": BuildDeps,
    }

setup(name="petmail",
      description="Secure messaging and files",
      author="Brian Warner",
      author_email="warner-petmail@lothar.com",
      license="MIT",
      url="https://github.com/warner/petmail",
      cmdclass=commands,
      )
