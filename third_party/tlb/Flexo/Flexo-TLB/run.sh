#!/bin/bash

FOLDER="$1"
shift

(
	podman run -i -t --rm \
	--mount type=bind,source="$(pwd)"/,target=/flexo \
	flexo \
	bash -c "cd /flexo && \\
		\"./build.sh\"
	"
) &&
(
	podman run -i -t --rm \
	--mount type=bind,source="$(pwd)"/,target=/flexo \
	flexo \
	bash -c "cd /flexo && \\
		\"/flexo/$FOLDER/build.sh\"
	"
) &&
(
	for file in $(ls -v "$FOLDER"/*.elf 2>/dev/null); do
		if [[ -x "$file" ]]; then
			taskset -c 7 ./"$file" "$@"
		else
			echo "Skipping $file (not executable)"
		fi
	done
)
