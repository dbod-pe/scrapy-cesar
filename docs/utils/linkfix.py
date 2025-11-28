#!/usr/bin/python

"""

Linkfix - a companion to sphinx's linkcheck builder.

Uses the linkcheck's output file to fix links in docs.

Originally created for this issue:
https://github.com/scrapy/scrapy/issues/606

Author: dufferzafar
"""

import re
import sys
from pathlib import Path
from typing import List, Optional


class LinkFixer:
    def __init__(self):
        self.current_filename: Optional[str] = None
        self.current_content: Optional[str] = None
        # A regex that matches standard linkcheck output lines
        self.line_re = re.compile(r"(.*)\:\d+\:\s\[(.*)\]\s(?:(.*)\sto\s(.*)|(.*))")

    def fix_links(self, output_lines: List[str]) -> None:
        for line in output_lines:
            match = self.line_re.match(line)
            if not match:
                print(f"Not Understood: {line.strip()}")
                continue

            self._process_match(match, line)

        self._flush_current_file()

    def _process_match(self, match, original_line: str) -> None:
        filename = match.group(1)
        error_type = match.group(2)

        if error_type.lower() in ["broken", "local"]:
            print(f"Not Fixed: {original_line.strip()}")
            return

        if filename != self.current_filename:
            self._flush_current_file()
            self._load_file(filename)

        if self.current_content:
            self.current_content = self.current_content.replace(
                match.group(3), match.group(4)
            )

    def _load_file(self, filename: str) -> None:
        self.current_filename = filename
        try:
            self.current_content = Path(filename).read_text(encoding="utf-8")
        except OSError as e:
            print(f"Error reading {filename}: {e}")
            self.current_filename = None
            self.current_content = None

    def _flush_current_file(self) -> None:
        if self.current_filename and self.current_content:
            Path(self.current_filename).write_text(self.current_content, encoding="utf-8")


def main():
    try:
        with Path("build/linkcheck/output.txt").open(encoding="utf-8") as out:
            output_lines = out.readlines()
    except OSError:
        print("linkcheck output not found; please run linkcheck first.")
        sys.exit(1)

    fixer = LinkFixer()
    fixer.fix_links(output_lines)


if __name__ == "__main__":
    main()
