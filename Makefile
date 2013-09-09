
all:
	@echo "Please read docs/build.rst and use setup.py instead."
	@echo "This Makefile only contains some shortcuts for use during development"
	exit 1

BASEURL="`./bin/petmail -d relay print-baseurl`"

.PHONY: relay n1 n2 stop bounce-all bounce rebuild
relay:
	-./bin/petmail stop relay
	rm -rf relay
	./bin/petmail create-relay relay
n1:
	-./bin/petmail stop n1
	rm -rf n1
	./bin/petmail create-node -r $(BASEURL) n1
n2:
	-./bin/petmail stop n2
	rm -rf n2
	./bin/petmail create-node -r $(BASEURL) n2

stop:
	-./bin/petmail stop n1
	-./bin/petmail stop n2
	-./bin/petmail stop relay
bounce-all:
	-./bin/petmail restart relay
	-./bin/petmail restart n1
	-./bin/petmail restart n2
bounce:
	-./bin/petmail restart n1
	-./bin/petmail restart n2

rebuild: stop relay n1 n2
	rm -rf .rendezvous
	$(MAKE) bounce-all

# do this before 'connect'
enable-local-mailbox:
	./bin/petmail enable-local-mailbox -d n1
	./bin/petmail enable-local-mailbox -d n2

connect:
	./bin/petmail invite -d n1 -n Bob code
	./bin/petmail invite -d n2 -n Alice code

dump-n1:
	sqlite3 n1/petmail.db .dump
dump-n2:
	sqlite3 n2/petmail.db .dump
PYTHON=deps-venv/bin/python
dump-ren:
	$(PYTHON) petmail/dump-messages.py .rendezvous
pyflakes:
	pyflakes petmail

# this is temporary, until there's an upstream release of pynacl that is
# pip-installable (without a system-wide libsodium)
install-pynacl:
	deps-venv/bin/pip install "https://github.com/warner/pynacl-1/zipball/embed4"

test-pynacl:
	$(PYTHON) -c "from nacl.public import PrivateKey; print PrivateKey.generate().encode().encode('hex');"
test:
	./bin/petmail test $(TEST)

.PHONY: test-coverage coverage-html open-coverage
test-coverage:
	coverage run ./bin/petmail test $(TEST)
coverage-html:
	rm -rf .coverage-html
	coverage html -d .coverage-html --include="petmail/*"
open-coverage:
	open .coverage-html/index.html
# you may need to run "deps-venv/bin/pip install coverage" to use this,
# and you'll want to load misc/coverage.el in your emacs.
.coverage.el: .coverage misc/coverage2el.py
	python misc/coverage2el.py

# TODO: use virtualenv.create_bootstrap_script(extra_text) to create a new
# modified virtualenv.py . Define an after_install(options,home_dir) function
# to edit home_dir/bin/activate to append lines to set and export CFLAGS and
# LDFLAGS. Bonus points for editing bin/activate to unset them in
# deactivate().

# patch-activate is a quick hack to patch activate, without unset/deactivate
patch-activate:
	echo >> deps-venv/bin/activate
	echo "CFLAGS=-I/usr/local/stow/libsodium-0.4.2/include" >>deps-venv/bin/activate
	echo "export CFLAGS" >>deps-venv/bin/activate
	echo "LDFLAGS=-L/usr/local/stow/libsodium-0.4.2/lib" >>deps-venv/bin/activate
	echo "export LDFLAGS" >>deps-venv/bin/activate
