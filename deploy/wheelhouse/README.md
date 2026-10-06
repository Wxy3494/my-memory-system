# Optional offline Linux wheels

Wheel binaries are downloaded here only for Docker builds with container DNS unavailable.
They are ignored by Git. The normal Dockerfile.memory installs from the configured package index.
Use Dockerfile.memory-offline after downloading the matching Linux cp313 wheels as documented
in docs/memory-deployment.md. Never put credentials or platform memory in this directory.
