PYTHON ?= python
ARGS ?=
.PHONY: data evaluate verify

data:
	$(PYTHON) -m saayashift.cli data $(ARGS)

evaluate:
	$(PYTHON) -m saayashift.cli evaluate $(ARGS)

verify:
	$(PYTHON) -m saayashift.cli verify $(ARGS)
