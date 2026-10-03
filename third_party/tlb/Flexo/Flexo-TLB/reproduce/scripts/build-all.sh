#!/bin/bash

PROJECT_ROOT=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )/../../

# build the Flexo compiler
# podman build -t flexo $PROJECT_ROOT
podman run -i -t --rm \
  --mount type=bind,source="$PROJECT_ROOT"/,target=/flexo \
  flexo \
  bash -c "cd /flexo && ./build.sh"

# build circuits
podman run -i -t --rm \
  --mount type=bind,source="$PROJECT_ROOT"/,target=/flexo \
  flexo \
  bash -c "cd /flexo/reproduce && ./scripts/compile-circuits.sh"
