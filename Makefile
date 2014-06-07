
all:
	@echo "Please read docs/build.rst and use setup.py instead."
	@echo "This Makefile only contains some shortcuts for use during development"
	exit 1

# this python knows to look in venv for our dependencies
PYTHON=venv/bin/python

BASEURL="`./bin/petmail -d relay print-baseurl`"

.PHONY: relay n1 n2 n3 s4 stop bounce-all bounce rebuild
relay:
	-./bin/petmail stop relay
	rm -rf relay
	./bin/petmail create-relay relay
n1:
	-./bin/petmail stop n1
	rm -rf n1
	./bin/petmail create-node --relay-url=$(BASEURL) --local-mailbox n1
n2:
	-./bin/petmail stop n2
	rm -rf n2
	./bin/petmail create-node --relay-url=$(BASEURL) --local-mailbox n2
n3:
	-./bin/petmail stop n3
	rm -rf n3
	./bin/petmail create-node --relay-url=$(BASEURL) n3
s4:
	-./bin/petmail stop s4
	rm -rf s4
	./bin/petmail create-node --relay-url=$(BASEURL) --local-mailbox s4

stop:
	-./bin/petmail stop n1
	-./bin/petmail stop n2
	-./bin/petmail stop n3
	-./bin/petmail stop s4
	-./bin/petmail stop relay
bounce-all:
	-./bin/petmail restart relay
	-./bin/petmail restart n1
	-./bin/petmail restart n2
	-./bin/petmail restart n3
	-./bin/petmail restart s4
bounce:
	-./bin/petmail restart n1
	-./bin/petmail restart n2
	-./bin/petmail restart n3
	-./bin/petmail restart s4

rebuild: stop relay n1 n2 n3 s4
	rm -rf .rendezvous
	$(MAKE) bounce-all

# ./s4/petmail offer-mailbox carol -> CODE
# ./n3/petmail accept-mailbox CODE

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

test-pynacl:
	$(PYTHON) -c "from nacl.public import PrivateKey; print PrivateKey.generate().encode().encode('hex');"
test:
	./bin/petmail test $(TEST)

.PHONY: test-coverage coverage-html open-coverage
test-coverage:
	coverage run ./bin/petmail test $(TEST)
coverage-html:
	rm -rf .coverage-html
	coverage html -d .coverage-html --include="petmail/*" --omit="petmail/test/*,petmail/_version.py"
open-coverage:
	open .coverage-html/index.html
# you may need to run "venv/bin/pip install coverage" to use this,
# and you'll want to load misc/coverage.el in your emacs.
.coverage.el: .coverage misc/coverage2el.py
	python misc/coverage2el.py
