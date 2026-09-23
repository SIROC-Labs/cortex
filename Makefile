TEST_DIRS := $(shell find plugins -type d -name tests | sort)

.PHONY: test
test:
	@status=0; for d in $(TEST_DIRS); do \
	  echo "== $$d"; \
	  python3 -m unittest discover -s $$d -p 'test_*.py' -v || status=1; \
	done; exit $$status
