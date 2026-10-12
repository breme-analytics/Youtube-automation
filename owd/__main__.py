import sys

from owd.cli import main

# Show each progress line as it happens, even when output goes to a file or a CI log.
sys.stdout.reconfigure(line_buffering=True)
main()
