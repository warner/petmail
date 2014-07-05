
all:
	@echo "Please read docs/build.rst and use setup.py instead."
	@echo "This Makefile only contains some shortcuts for use during development"
	exit 1

# this python knows to look in venv for our dependencies
PYTHON=venv/bin/python

BASEURL="`./relay/petmail print-baseurl`"

.PHONY: relay n1 n2 n3 s4 stop bounce-all bounce rebuild
relay:
	-./relay/petmail stop relay
	rm -rf relay
	./bin/petmail create-relay relay
n1:
	-./n1/petmail stop n1
	rm -rf n1
	./bin/petmail create-node --relay-url=$(BASEURL) --local-mailbox n1
n2:
	-./n2/petmail stop n2
	rm -rf n2
	./bin/petmail create-node --relay-url=$(BASEURL) --local-mailbox n2
n3:
	-./n3/petmail stop n3
	rm -rf n3
	./bin/petmail create-node --relay-url=$(BASEURL) n3
s4:
	-./bin/petmail stop s4
	rm -rf s4
	./bin/petmail create-node --relay-url=$(BASEURL) --local-mailbox s4

stop:
	-./n1/petmail stop n1
	-./n2/petmail stop n2
	-./n3/petmail stop n3
	-./s4/petmail stop s4
	-./relay/petmail stop relay
bounce-all:
	-./relay/petmail restart relay
	-./n1/petmail restart n1
	-./n2/petmail restart n2
	-./n3/petmail restart n3
	-./s4/petmail restart s4
bounce:
	-./n1/petmail restart n1
	-./n2/petmail restart n2
	-./n3/petmail restart n3
	-./s4/petmail restart s4

rebuild: stop
	rm -rf .rendezvous relay n1 n2 n3 s4
	$(MAKE) relay n1 n2 n3 s4
	$(MAKE) bounce-all

# ./s4/petmail offer-mailbox carol -> CODE
# ./n3/petmail accept-mailbox CODE

connect:
	./n1/petmail invite -n Bob code1
	./n2/petmail invite -n Alice code1
	./n1/petmail invite -n Carol code2
	./n3/petmail invite -n Alice code2
	./n2/petmail invite -n Carol code3
	./n3/petmail invite -n Bob code3

dump-n1:
	sqlite3 n1/petmail.db .dump
dump-n2:
	sqlite3 n2/petmail.db .dump
dump-ren:
	$(PYTHON) petmail/dump-messages.py .rendezvous
clear-n1:
	sqlite3 n1/petmail.db "DELETE FROM invitations; DELETE FROM addressbook; DELETE FROM inbound_messages;"
clear-n2:
	sqlite3 n2/petmail.db "DELETE FROM invitations; DELETE FROM addressbook; DELETE FROM inbound_messages;"

pyflakes:
	pyflakes petmail

test-pynacl:
	$(PYTHON) -c "from nacl.public import PrivateKey; print PrivateKey.generate().encode().encode('hex');"
test:
	./bin/petmail test $(TEST)

# to use "coverage", it must be installed into the venv, since "coverage run"
# needs to both import the coverage library and the petmail code.
.PHONY: test-coverage coverage-html open-coverage
venv/bin/coverage:
	venv/bin/pip install coverage
test-coverage: venv/bin/coverage
	venv/bin/coverage run ./venv/bin/petmail test $(TEST)
coverage-html: venv/bin/coverage
	rm -rf .coverage-html
	venv/bin/coverage html -d .coverage-html --include="petmail/*" --omit="petmail/test/*,petmail/_version.py"
open-coverage:
	open .coverage-html/index.html
# you'll want to load misc/coverage.el in your emacs
.coverage.el: .coverage misc/coverage2el.py venv/bin/coverage
	venv/bin/python misc/coverage2el.py
