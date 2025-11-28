import os
import shutil
from pathlib import Path
import sys

# Mock the linkfix module import or run it as a subprocess
# Since linkfix.py has a main() function and uses sys.argv/files, we can import it if we are careful,
# or better, run it as a script. Given it's a standalone script, subprocess is safer but import is easier for debugging.
# Let's try to import it, but we need to make sure we are in the right directory or mock the paths.
# linkfix.py hardcodes "build/linkcheck/output.txt".

def setup_environment():
    # Create necessary directories
    os.makedirs("build/linkcheck", exist_ok=True)
    os.makedirs("docs/source", exist_ok=True)

    # Create a dummy file to be fixed
    Path("docs/source/test_file.rst").write_text("Check out this link: https://example.com/old", encoding="utf-8")
    
    # Create the linkcheck output file
    # Format: filename:lineno: [status] link to new_link
    # Example from code regex: (.*)\:\d+\:\s\[(.*)\]\s(?:(.*)\sto\s(.*)|(.*))
    # docs/source/test_file.rst:1: [redirect] https://example.com/old to https://example.com/new
    
    linkcheck_output = "docs/source/test_file.rst:1: [redirect] https://example.com/old to https://example.com/new\n"
    Path("build/linkcheck/output.txt").write_text(linkcheck_output, encoding="utf-8")

def cleanup_environment():
    shutil.rmtree("build", ignore_errors=True)
    shutil.rmtree("docs/source", ignore_errors=True)
    # Also clean up if they were created in root
    if os.path.exists("docs/source"):
        shutil.rmtree("docs")

def run_linkfix():
    # We need to add the directory containing linkfix.py to sys.path
    # Assuming this script is run from the project root
    sys.path.append("docs/utils")
    import linkfix
    
    # linkfix.main() doesn't take arguments, it reads from hardcoded path.
    # We are simulating running from project root.
    try:
        linkfix.main()
    except SystemExit as e:
        if e.code != 0:
            print(f"linkfix failed with exit code {e.code}")

def verify_fix():
    content = Path("docs/source/test_file.rst").read_text(encoding="utf-8")
    expected = "Check out this link: https://example.com/new"
    if content == expected:
        print("SUCCESS: File was updated correctly.")
    else:
        print(f"FAILURE: File content mismatch.\nExpected: {expected}\nActual:   {content}")

if __name__ == "__main__":
    try:
        setup_environment()
        run_linkfix()
        verify_fix()
    finally:
        # cleanup_environment() # Keep it for inspection if needed
        pass
