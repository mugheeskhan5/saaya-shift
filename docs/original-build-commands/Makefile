PYTHON ?= python
.PHONY: data evaluate test dashboard verify
data:
	$(PYTHON) -m saayashift.cli data
evaluate:
	$(PYTHON) -m saayashift.cli evaluate
test:
	$(PYTHON) -m pytest -q
dashboard:
	$(PYTHON) -m streamlit run app.py
verify:
	$(PYTHON) -m saayashift.cli verify
