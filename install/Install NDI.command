#!/bin/sh
# Double-click this file in the Finder to install NDI (macOS).
#
# It runs install-ndi.sh from the same folder, or downloads it if this file
# was saved on its own, and keeps the Terminal window open at the end so you
# can read what happened. The first time, macOS may refuse to open it
# because it was downloaded: right-click (or Control-click) it, choose Open,
# then Open again. See README.md in this folder.

URL="https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.sh"

cd "$(dirname "$0")" || exit 1
if [ -f ./install-ndi.sh ]; then
    sh ./install-ndi.sh "$@"
    status=$?
else
    tmp=$(mktemp) || exit 1
    if curl --proto '=https' --tlsv1.2 -LsSf "$URL" -o "$tmp"; then
        sh "$tmp" "$@"
        status=$?
    else
        echo "NDI install failed: could not download install-ndi.sh (check your connection)" >&2
        status=1
    fi
    rm -f "$tmp"
fi

echo
if [ "$status" -eq 0 ]; then
    echo "Done."
else
    echo "NDI was not installed; the reason is above."
fi
printf 'Press Return to close this window. '
read -r _
exit "$status"
