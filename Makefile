
all:
	@echo "Please read docs/build.rst and use setup.py instead."
	@echo "This Makefile only contains some shortcuts for use during development"
	exit 1

.PHONY: n1 n2 relay stop bounce-all bounce rebuild
n1:
	-./bin/petmail stop n1
	rm -rf n1
	./bin/petmail create-node n1
n2:
	-./bin/petmail stop n2
	rm -rf n2
	./bin/petmail create-node n2
#relay:
#	-./bin/petmail stop relay
#	rm -rf relay
#	./bin/petmail create-relay relay

stop:
	-./bin/petmail stop n1
	-./bin/petmail stop n2
#	-./bin/petmail stop relay
bounce-all:
#	-./bin/petmail restart relay
#	sleep 1
	-./bin/petmail restart n1
	-./bin/petmail restart n2
bounce:
	-./bin/petmail restart n1
	-./bin/petmail restart n2

rebuild: stop n1 n2
	rm -rf .rendezvous
	$(MAKE) bounce

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
dump-ren:
	deps-venv/bin/python petmail/dump-messages.py .rendezvous
pyflakes:
	pyflakes petmail

# 1st: in libsodium-0.4.2: ./configure --prefix=/usr/local/stow/libsodium-0.4.2
#      make, make check, make install
WLS1=CFLAGS=-I/usr/local/stow/libsodium-0.4.2/include LDFLAGS=-L/usr/local/stow/libsodium-0.4.2/lib
#WLS2=LD_LIBRARY_PATH=/usr/local/stow/libsodium-0.4.2/lib
install-pynacl:
	$(WLS1) deps-venv/bin/pip install PyNaCl
PYTHON=deps-venv/bin/python
test-pynacl:
	$(WLS1) $(PYTHON) -c "from nacl.public import PrivateKey; print PrivateKey.generate().encode().encode('hex');"
test:
	$(WLS1) ./bin/petmail test $(TEST)

.PHONY: test-coverage coverage-html open-coverage
test-coverage:
	$(WLS1) coverage run ./bin/petmail test $(TEST)
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
