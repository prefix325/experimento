DOCS=preproject article dissertation doctoral-agenda

render:
	python tools/render_documents.py

check-projection:
	python tools/render_documents.py --check

validate: check-projection
	python tools/validate_repository.py

build: check-projection
	@for d in $(DOCS); do (cd deliverables/$$d && latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex) || exit 1; done

clean:
	@for d in $(DOCS); do (cd deliverables/$$d && latexmk -C main.tex); done
