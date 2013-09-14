
all:
	@echo "Please read docs/build.rst and use setup.py instead."
	@echo "This Makefile only contains some shortcuts for use during development"
	exit 1

# this python knows to look in deps-venv for our dependencies
PYTHON=deps-venv/bin/python

BASEURL="`./bin/petmail -d relay print-baseurl`"

.PHONY: relay n1 n2 n3 stop bounce-all bounce rebuild
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
n3:
	-./bin/petmail stop n3
	rm -rf n3
	./bin/petmail create-node -r $(BASEURL) n3

stop:
	-./bin/petmail stop n1
	-./bin/petmail stop n2
	-./bin/petmail stop n3
	-./bin/petmail stop relay
bounce-all:
	-./bin/petmail restart relay
	-./bin/petmail restart n1
	-./bin/petmail restart n2
	-./bin/petmail restart n3
bounce:
	-./bin/petmail restart n1
	-./bin/petmail restart n2
	-./bin/petmail restart n3

rebuild: stop relay n1 n2 n3
	rm -rf .rendezvous
	$(MAKE) bounce-all

# do this before 'connect'
enable-local-mailbox:
	./bin/petmail enable-local-mailbox -d n1
	./bin/petmail enable-local-mailbox -d n2
	./bin/petmail enable-local-mailbox -d n3

connect:
	./bin/petmail invite -d n1 -n Bob code1
	./bin/petmail invite -d n2 -n Alice code1
	./bin/petmail invite -d n1 -n Carol code2
	./bin/petmail invite -d n3 -n Alice code2
	./bin/petmail invite -d n2 -n Carol code3
	./bin/petmail invite -d n3 -n Bob code3

dump-n1:
	sqlite3 n1/petmail.db .dump
dump-n2:
	sqlite3 n2/petmail.db .dump
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
