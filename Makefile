SWH_WEB_VERSION ?= 0.17.12
IMAGE ?= swh-openapi-gen
# swh.search publishes wheels for linux/amd64 only, and its sdist build needs
# a JavaScript toolchain, so generation does not run natively on other hosts.
PLATFORM ?= linux/amd64
RUN = docker run --rm --platform $(PLATFORM) -v "$(CURDIR):/gen" $(IMAGE)
GENERATE = -e DJANGO_SETTINGS_MODULE=settings -e PYTHONPATH=/gen/generator

.PHONY: all image spec generate overlay validate test drift clean

all: spec validate test

image:
	docker build --platform $(PLATFORM) \
		--build-arg SWH_WEB_VERSION=$(SWH_WEB_VERSION) -t $(IMAGE) .

spec: generate overlay

generate:
	docker run --rm --platform $(PLATFORM) -v "$(CURDIR):/gen" $(GENERATE) \
		$(IMAGE) python generator/generate.py -o openapi.gen.yaml

overlay:
	$(RUN) python generator/overlay.py openapi.gen.yaml overlay.yaml -o openapi.yaml

validate:
	$(RUN) python -m openapi_spec_validator openapi.yaml

test:
	$(RUN) python -m pytest tests/ -q

drift:
	$(RUN) python generator/drift.py openapi.yaml

clean:
	rm -f openapi.gen.yaml openapi.yaml
