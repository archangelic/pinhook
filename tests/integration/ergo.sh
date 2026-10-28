#!/usr/bin/env bash
# Starts a local Ergo IRC server for pinhook's integration tests.
#
#   tests/integration/ergo.sh [folder]     (default folder: .ergo)
#
# Stop it with: kill "$(cat .ergo/ergo.pid)"
set -euo pipefail

VERSION=2.19.1
DIR=${1:-.ergo}

case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) PLATFORM=linux-x86_64 ;;
    Linux-aarch64) PLATFORM=linux-arm64 ;;
    Darwin-arm64) PLATFORM=macos-arm64 ;;
    Darwin-x86_64) PLATFORM=macos-x86_64 ;;
    *) echo "there's no Ergo build for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac
NAME=ergo-$VERSION-$PLATFORM

mkdir -p "$DIR"
cd "$DIR"
if [ ! -x ergo ]; then
    URL=https://github.com/ergochat/ergo/releases/download/v$VERSION
    curl -sSfLO "$URL/$NAME.tar.gz"
    curl -sSfLO "$URL/ergo-$VERSION-checksums.txt"
    # stop here if the download doesn't match the release's published checksum
    grep " $NAME.tar.gz\$" "ergo-$VERSION-checksums.txt" > "$NAME.sha256"
    if command -v sha256sum > /dev/null; then sha256sum -c "$NAME.sha256"; else shasum -a 256 -c "$NAME.sha256"; fi
    tar -xzf "$NAME.tar.gz" --strip-components=1
fi

# Ergo's defaults, except:
#   - its ssl port only listens on this machine
#   - logged-in users can change nick, like on Libera
#   - logins aren't throttled, since the tests log the same accounts in again and again
sed -e 's/^        ":6697":/        "127.0.0.1:6697":/' \
    -e 's/^        force-nick-equals-account: true$/        force-nick-equals-account: false/' \
    -e '/^    login-throttling:/,/enabled:/ s/enabled: true/enabled: false/' \
    default.yaml > ircd.yaml

[ -f fullchain.pem ] || ./ergo mkcerts --conf ircd.yaml --quiet
[ -f ircd.db ] || ./ergo initdb --conf ircd.yaml --quiet

./ergo run --conf ircd.yaml > ergo.log 2>&1 &
echo $! > ergo.pid
for _ in $(seq 1 50); do
    if (echo > /dev/tcp/127.0.0.1/6667) 2> /dev/null; then
        echo "Ergo $VERSION is running on 127.0.0.1 (6667, and 6697 with ssl)"
        exit 0
    fi
    sleep 0.1
done
echo "Ergo didn't start, see $DIR/ergo.log" >&2
exit 1
